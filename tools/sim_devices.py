#!/usr/bin/env python3
"""
Hardware simulator: pretends to be BOTH boards, speaking the exact firmware
protocol, so the server + dashboard can be tested with no hardware.

  sim ESP32   : WebSocket to the server (hello, 1 Hz status, peer events),
                relays START to the sim ESP8266 over UDP, streams MPU6050 data
  sim ESP8266 : UDP heartbeats, ACK, PPG + GSR samples as ADS1115 counts

Signal source:
  --source synthetic            synthetic pulse/GSR/motion (--hr sets the BPM)
  --source wesad --subject 2 --condition stress|baseline|amusement
                                replays real E4 wrist data from WESAD, converted
                                back into raw sensor units (needs tools/ml/cache)

    python tools/sim_devices.py --source wesad --condition stress
    python tools/sim_devices.py --say "measure my stress level"   # also triggers it
    python tools/sim_devices.py --loss 0.03                       # 3 % packet loss
    python tools/sim_devices.py --no-esp32                        # test direct fallback
"""
import argparse
import asyncio
import json
import random
import socket
import time
from pathlib import Path

import numpy as np
import websockets

HERE = Path(__file__).resolve().parent
SERVER = "127.0.0.1"


class UdpInbox(asyncio.DatagramProtocol):
    """Queue-backed receiver (loop.sock_recvfrom needs Python 3.11)."""
    def __init__(self):
        self.q: asyncio.Queue = asyncio.Queue()

    def datagram_received(self, data, addr):
        self.q.put_nowait((data, addr))


async def open_inbox(sock):
    loop = asyncio.get_running_loop()
    inbox = UdpInbox()
    await loop.create_datagram_endpoint(lambda: inbox, sock=sock)
    return inbox
FSR, VCC, CAL = 4.096, 3.3, 512.0


def us_to_counts(us: np.ndarray) -> np.ndarray:
    """Invert the Grove formula: conductance (uS) -> 10-bit X -> ADS1115 counts."""
    r = 1e6 / np.clip(us, 0.05, None)
    x = (r * CAL - 10240000.0) / (r + 20000.0)
    return np.clip(x / 1023.0 * VCC / FSR * 32768.0, 0, 32767)


class SignalSource:
    def __init__(self, args):
        self.args = args
        if args.source == "wesad":
            d = np.load(HERE / "ml" / "cache" / f"S{args.subject}_wrist.npz")
            code = {"baseline": 1, "stress": 2, "amusement": 3}[args.condition]
            lab = d["label_bvp"]
            idx = np.where(lab == code)[0]
            start = idx[len(idx) // 4] / 64.0          # a bit into the condition
            self.t0 = start
            self.bvp, self.eda, self.acc = d["bvp"], d["eda"], d["acc"]
            print(f"[sim] WESAD S{args.subject} {args.condition} from t={start:.0f}s")

    def vitals(self, i: int) -> tuple[int, int]:
        t = i / 64.0
        if self.args.source == "wesad":
            k = int((self.t0 + t) * 64)
            ppg = 16000 + 60.0 * self.bvp[k % len(self.bvp)]
            eda = self.eda[int((self.t0 + t) * 4) % len(self.eda)]
        else:
            hr = self.args.hr + 3 * np.sin(2 * np.pi * 0.1 * t)
            ph = (t * hr / 60.0) % 1.0
            ppg = 16000 + 3000 * np.exp(-((ph - 0.2) / 0.07) ** 2) + 1200 * np.exp(-((ph - 0.45) / 0.1) ** 2)
            ppg += random.gauss(0, 60)
            eda = 4.0 + 0.3 * np.sin(2 * np.pi * t / 40) + (0.4 if (t % 17) < 3 else 0)
        return int(np.clip(ppg, -32768, 32767)), int(us_to_counts(np.array([eda]))[0])

    def motion(self, i: int):
        t = i / 32.0
        if self.args.source == "wesad":
            a = self.acc[int((self.t0 + t) * 32) % len(self.acc)]
            ax, ay, az = float(a[0]), float(a[1]), float(a[2])
        else:
            ax, ay, az = (random.gauss(0.02, 0.01), random.gauss(-0.1, 0.01), random.gauss(0.99, 0.01))
        return ax, ay, az, random.gauss(0, 1), random.gauss(0, 1), random.gauss(0, 1)


# ---------------------------------------------------------------------------
class SimESP8266:
    def __init__(self, src: SignalSource, loss: float):
        self.src, self.loss = src, loss
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("0.0.0.0", 4210))
        self.sock.setblocking(False)
        self.collecting = None
        self.samples = 0
        self.last_ppg, self.last_gsr = 16000, 9000

    async def run(self):
        inbox = await open_inbox(self.sock)
        asyncio.create_task(self.heartbeat())
        while True:
            data, addr = await inbox.q.get()
            msg = data.decode().strip()
            if msg.startswith("START,"):
                _, mid, dur, ip, port = msg.split(",")
                self.sock.sendto(f"ACK,{mid}".encode(), addr)
                if self.collecting and self.collecting["id"] == mid:
                    continue
                if self.collecting:
                    self.collecting["task"].cancel()
                print(f"[sim8266] START {mid} {dur} ms -> {ip}:{port}  (LED ON)")
                c = {"id": mid, "cmd": addr}
                c["task"] = asyncio.create_task(self.stream(c, int(dur) / 1000, ip, int(port)))
                self.collecting = c
            elif msg.startswith("STOP"):
                if self.collecting:
                    self.collecting["task"].cancel()
                    print("[sim8266] STOP (LED OFF)")
                    self.collecting = None

    async def stream(self, c, dur, ip, port):
        t0 = time.monotonic()
        i = 0
        try:
            while time.monotonic() - t0 < dur:
                due = t0 + (i + 8) / 64.0
                await asyncio.sleep(max(0, due - time.monotonic()))
                vals = [self.src.vitals(i + k) for k in range(8)]
                self.last_ppg, self.last_gsr = vals[-1]
                if random.random() >= self.loss:
                    body = ",".join(f"{p},{g}" for p, g in vals)
                    self.sock.sendto(f"P,{c['id']},{i},8,{body}".encode(), (ip, port))
                i += 8
                self.samples = i
            self.sock.sendto(f"DONE,{c['id']},{i}".encode(), c["cmd"])
            print(f"[sim8266] done {i} samples (LED OFF)")
        finally:
            if self.collecting is c:
                self.collecting = None

    async def heartbeat(self):
        while True:
            c = self.collecting
            hb = (f"HB,esp8266,-52,{1 if c else 0},{int(time.monotonic())},{self.last_ppg},"
                  f"{self.last_gsr},1,{c['id'] if c else '-'},{self.samples}")
            self.sock.sendto(hb.encode(), (SERVER, 4212))
            if hasattr(self, "esp32_port"):
                self.sock.sendto(hb.encode(), ("127.0.0.1", self.esp32_port))
            await asyncio.sleep(1.0)


class SimESP32:
    def __init__(self, src: SignalSource, peer: SimESP8266, loss: float, say: str | None):
        self.src, self.peer, self.loss, self.say = src, peer, loss, say
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))           # NOT 4212: the server owns it here
        self.sock.setblocking(False)
        peer.esp32_port = self.sock.getsockname()[1]
        self.measuring = None
        self.peer_seen = 0.0
        self.peer_hb = ""
        self.motion_samples = 0

    async def run(self):
        while True:
            try:
                async with websockets.connect(f"ws://{SERVER}:8765/audio") as ws:
                    print("[sim32] connected to server")
                    await ws.send(json.dumps({"type": "hello", "device": "esp32-sim",
                                              "sample_rate": 16000}))
                    tasks = [asyncio.create_task(self.status(ws)),
                             asyncio.create_task(self.udp_rx(ws))]
                    if self.say:
                        tasks.append(asyncio.create_task(self.say_later()))
                    async for msg in ws:
                        if isinstance(msg, str):
                            await self.on_cmd(ws, json.loads(msg))
            except (OSError, websockets.ConnectionClosed) as e:
                print(f"[sim32] server not reachable ({e.__class__.__name__}), retrying in 2 s")
                await asyncio.sleep(2)

    async def say_later(self):
        await asyncio.sleep(2.5)
        import urllib.request
        req = urllib.request.Request("http://127.0.0.1:8080/api/say", method="POST",
                                     data=json.dumps({"text": self.say}).encode(),
                                     headers={"Content-Type": "application/json"})
        await asyncio.to_thread(urllib.request.urlopen, req)
        print(f"[sim32] said: {self.say!r}")
        self.say = None

    async def on_cmd(self, ws, m):
        if m.get("type") == "measure_start":
            mid, dur = m["id"], m["duration_ms"]
            print(f"[sim32] measure_start {mid} -> relaying START to ESP8266")
            self.measuring = {"id": mid, "acked": False}
            await ws.send(json.dumps({"type": "peer_event", "event": "started", "id": mid, "mpu": True}))
            for tries in range(1, 7):
                self.sock.sendto(f"START,{mid},{dur},127.0.0.1,4211".encode(), ("127.0.0.1", 4210))
                await asyncio.sleep(0.25)
                if self.measuring and self.measuring["acked"]:
                    await ws.send(json.dumps({"type": "peer_event", "event": "ack", "id": mid,
                                              "tries": tries, "peer_ip": "127.0.0.1"}))
                    break
            else:
                await ws.send(json.dumps({"type": "peer_event", "event": "no_ack", "id": mid}))
            asyncio.create_task(self.motion(ws, mid, dur / 1000))
        elif m.get("type") == "measure_stop":
            if self.measuring:
                self.sock.sendto(f"STOP,{self.measuring['id']}".encode(), ("127.0.0.1", 4210))
            self.measuring = None

    async def motion(self, ws, mid, dur):
        t0 = time.monotonic()
        i = 0
        while self.measuring and self.measuring["id"] == mid and time.monotonic() - t0 < dur:
            due = t0 + (i + 8) / 32.0
            await asyncio.sleep(max(0, due - time.monotonic()))
            vals = [self.src.motion(i + k) for k in range(8)]
            if random.random() >= self.loss:
                body = ",".join(",".join(f"{v:.4f}" for v in s) for s in vals)
                self.sock.sendto(f"A,{mid},{i},8,{body}".encode(), (SERVER, 4213))
            i += 8
            self.motion_samples = i
        await ws.send(json.dumps({"type": "peer_event", "event": "motion_done", "id": mid,
                                  "reason": "duration elapsed", "motion_samples": i}))
        self.measuring = None

    async def udp_rx(self, ws):
        if not hasattr(self, "inbox"):
            self.inbox = await open_inbox(self.sock)
        while True:
            data, _ = await self.inbox.q.get()
            msg = data.decode()
            if msg.startswith("HB,"):
                self.peer_seen, self.peer_hb = time.monotonic(), msg
            elif msg.startswith("ACK,") and self.measuring and msg[4:] == self.measuring["id"]:
                self.measuring["acked"] = True
            elif msg.startswith("DONE,"):
                await ws.send(json.dumps({"type": "peer_event", "event": "peer_done",
                                          "id": msg.split(",")[1], "peer_samples": int(msg.split(",")[2])}))

    async def status(self, ws):
        t0 = time.monotonic()
        while True:
            p = self.peer_hb.split(",") if self.peer_hb else []
            online = time.monotonic() - self.peer_seen < 3.5
            a = self.src.motion(int((time.monotonic() - t0) * 32))
            level = abs(random.gauss(0.003, 0.001))
            await ws.send(json.dumps({
                "type": "status", "device": "esp32", "ip": "127.0.0.1", "rssi": -58,
                "uptime": int(time.monotonic() - t0), "heap": 180000, "mic_ok": True,
                "mic_level": level, "speech": 0, "utterances": 0, "mpu_ok": True,
                "acc": [round(a[0], 3), round(a[1], 3), round(a[2], 3)],
                "measuring": bool(self.measuring), "id": self.measuring["id"] if self.measuring else "",
                "motion_samples": self.motion_samples,
                "peer": {"online": online, "ip": "127.0.0.1", "rssi": int(p[2]) if p else 0,
                         "collecting": p[3] == "1" if p else False, "ppg": int(p[5]) if p else 0,
                         "gsr": int(p[6]) if p else 0, "ads": True, "age_ms": 0, "hb": 0},
            }))
            await asyncio.sleep(1.0)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["synthetic", "wesad"], default="synthetic")
    ap.add_argument("--subject", type=int, default=2)
    ap.add_argument("--condition", choices=["baseline", "stress", "amusement"], default="stress")
    ap.add_argument("--hr", type=float, default=72)
    ap.add_argument("--loss", type=float, default=0.0, help="UDP packet loss probability")
    ap.add_argument("--say", default=None, help="typed voice command sent after connecting")
    ap.add_argument("--no-esp32", action="store_true", help="only simulate the ESP8266")
    args = ap.parse_args()

    src = SignalSource(args)
    e8266 = SimESP8266(src, args.loss)
    tasks = [e8266.run()]
    if not args.no_esp32:
        tasks.append(SimESP32(src, e8266, args.loss, args.say).run())
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
