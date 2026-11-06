"""
UDP side of the laptop: receives ESP8266 vitals, ESP32 motion and ESP8266
heartbeats/ACKs, and keeps per-device health + link statistics.

Packet formats (see docs/PROTOCOL.md):
  4211  P,<id>,<first_idx>,<n>,<ppg0>,<gsr0>,...              ESP8266 -> laptop
  4213  A,<id>,<first_idx>,<n>,<ax>,<ay>,<az>,<gx>,<gy>,<gz>,... ESP32 -> laptop
  4212  HB,esp8266,<rssi>,<coll>,<up>,<ppg>,<gsr>,<ads>,<id>,<samples>
        ACK,<id>   DONE,<id>,<samples>   PONG,esp8266
"""
from __future__ import annotations

import asyncio
import socket
import time
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from . import config as C


@dataclass
class Stream:
    """Samples of one measurement, indexed by the device's sample counter."""
    fs: int
    width: int
    data: dict = field(default_factory=dict)      # idx -> tuple of values
    packets: int = 0
    first_rx: float = 0.0
    last_rx: float = 0.0

    def add(self, first: int, values: list[tuple]):
        now = time.monotonic()
        if not self.packets:
            self.first_rx = now
        self.packets += 1
        self.last_rx = now
        for i, v in enumerate(values):
            self.data[first + i] = v

    @property
    def max_index(self) -> int:
        return max(self.data) + 1 if self.data else 0

    def stats(self) -> dict:
        n = self.max_index
        got = len(self.data)
        return {"samples": got, "expected": n, "loss_pct": round(100 * (1 - got / n), 2) if n else 0.0,
                "packets": self.packets,
                "rate_hz": round(got / (self.last_rx - self.first_rx), 1)
                if self.last_rx > self.first_rx else 0.0}

    def array(self, n: int | None = None) -> tuple[np.ndarray, float]:
        """Dense (n, width) array; lost samples linearly interpolated. Returns (arr, loss_pct)."""
        n = n or self.max_index
        out = np.full((n, self.width), np.nan)
        for i, v in self.data.items():
            if i < n:
                out[i] = v
        missing = np.isnan(out[:, 0])
        loss = float(missing.mean() * 100) if n else 100.0
        if missing.all():
            return out, 100.0
        idx = np.arange(n)
        for j in range(self.width):
            col = out[:, j]
            m = np.isnan(col)
            if m.any():
                col[m] = np.interp(idx[m], idx[~m], col[~m])
        return out, loss


@dataclass
class DeviceState:
    name: str
    online: bool = False
    ip: str = ""
    rssi: int | None = None
    last_seen: float = 0.0
    info: dict = field(default_factory=dict)

    def touch(self, ip: str | None = None):
        self.last_seen = time.time()
        self.online = True
        if ip:
            self.ip = ip

    def to_dict(self, timeout: float) -> dict:
        age = time.time() - self.last_seen if self.last_seen else None
        online = bool(age is not None and age < timeout)
        return {"name": self.name, "online": online, "ip": self.ip, "rssi": self.rssi,
                "age_s": round(age, 1) if age is not None else None, **self.info}


class DeviceHub:
    """Owns the UDP sockets. `on_event(kind, payload)` feeds the dashboard."""

    def __init__(self, on_event: Callable[[str, dict], None]):
        self.on_event = on_event
        self.esp32 = DeviceState("esp32")
        self.esp8266 = DeviceState("esp8266")
        self.active_id: str | None = None
        self.vitals: Stream | None = None
        self.motion: Stream | None = None
        self.acks: dict[str, asyncio.Event] = {}
        self.done: dict[str, asyncio.Event] = {}
        self._status_tx = None
        self.hb_count = 0

    # ---------------------------------------------------------------- setup
    async def start(self):
        loop = asyncio.get_running_loop()
        await loop.create_datagram_endpoint(lambda: _Proto(self._on_vitals),
                                            local_addr=("0.0.0.0", C.PORT_VITALS))
        await loop.create_datagram_endpoint(lambda: _Proto(self._on_motion),
                                            local_addr=("0.0.0.0", C.PORT_MOTION))
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.bind(("0.0.0.0", C.PORT_STATUS))
        self._status_tx, _ = await loop.create_datagram_endpoint(
            lambda: _Proto(self._on_status), sock=sock)

    # ------------------------------------------------------- measurement io
    def arm(self, mid: str):
        self.active_id = mid
        self.vitals = Stream(C.FS_PPG, 2)
        self.motion = Stream(C.FS_ACC, 6)
        self.acks[mid] = asyncio.Event()
        self.done[mid] = asyncio.Event()

    def disarm(self):
        self.active_id = None

    def send_esp8266(self, msg: str, ip: str | None = None) -> bool:
        ip = ip or self.esp8266.ip
        if not ip or self._status_tx is None:
            return False
        # Sent from the status socket (port 4212) so the ACK comes back to it.
        self._status_tx.sendto(msg.encode(), (ip, C.PORT_ESP8266_CONTROL))
        return True

    # ------------------------------------------------------------ receivers
    def _on_vitals(self, data: bytes, addr):
        parts = data.decode(errors="ignore").strip().split(",")
        if len(parts) < 4 or parts[0] != "P":
            return
        self.esp8266.touch(addr[0])
        mid, first, n = parts[1], int(parts[2]), int(parts[3])
        vals = parts[4:4 + 2 * n]
        if mid != self.active_id or self.vitals is None or len(vals) != 2 * n:
            return
        samples = [(float(vals[2 * i]), float(vals[2 * i + 1])) for i in range(n)]
        self.vitals.add(first, samples)
        self.on_event("vitals", {"first": first, "ppg": [s[0] for s in samples],
                                 "gsr": [s[1] for s in samples]})

    def _on_motion(self, data: bytes, addr):
        parts = data.decode(errors="ignore").strip().split(",")
        if len(parts) < 4 or parts[0] != "A":
            return
        self.esp32.touch(addr[0])
        mid, first, n = parts[1], int(parts[2]), int(parts[3])
        vals = parts[4:4 + 6 * n]
        if mid != self.active_id or self.motion is None or len(vals) != 6 * n:
            return
        samples = [tuple(float(v) for v in vals[6 * i: 6 * i + 6]) for i in range(n)]
        self.motion.add(first, samples)
        self.on_event("motion", {"first": first, "acc": [s[:3] for s in samples]})

    def _on_status(self, data: bytes, addr):
        msg = data.decode(errors="ignore").strip()
        if msg.startswith("HB,esp8266,"):
            p = msg.split(",")
            try:
                self.esp8266.touch(addr[0])
                self.esp8266.rssi = int(p[2])
                self.esp8266.info.update({
                    "collecting": p[3] == "1", "uptime_s": int(p[4]), "ppg_raw": int(p[5]),
                    "gsr_raw": int(p[6]), "ads_ok": p[7] == "1", "samples": int(p[9]),
                })
                self.hb_count += 1
            except (IndexError, ValueError):
                pass
        elif msg.startswith("ACK,"):
            self.esp8266.touch(addr[0])
            ev = self.acks.get(msg[4:])
            if ev:
                ev.set()
                self.on_event("link", {"path": "laptop->esp8266", "event": "ack", "id": msg[4:]})
        elif msg.startswith("DONE,"):
            mid = msg.split(",")[1]
            ev = self.done.get(mid)
            if ev:
                ev.set()


class _Proto(asyncio.DatagramProtocol):
    def __init__(self, cb):
        self.cb = cb

    def datagram_received(self, data, addr):
        try:
            self.cb(data, addr)
        except Exception as e:                     # never kill the endpoint
            print(f"[hub] bad packet from {addr}: {e!r}")
