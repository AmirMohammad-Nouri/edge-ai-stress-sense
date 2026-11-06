#!/usr/bin/env python3
"""
Stress-measurement system server (laptop). One process, one asyncio loop:

  ws://:8765/audio   ESP32: speech audio in, status/peer events in, commands out
  udp :4211/:4213    ESP8266 PPG+GSR / ESP32 MPU6050 samples
  udp :4212          ESP8266 heartbeats + ACKs (broadcast)
  http://:8080       dashboard (live diagrams, signals, results)

Voice: STT (Moonshine) -> intent rules ("measure my stress level",
"calibrate my baseline", "stop") -> measurement; any other sentence goes to
the LLM agent (Ollama) as before. Every voice component is optional: if a
model is missing the rest keeps running and the dashboard says what is offline.

    python tools/stress_server.py                 # everything
    python tools/stress_server.py --no-voice      # dashboard + sensors only
    python tools/stress_server.py --no-llm        # voice commands, no chit-chat
    python tools/stress_server.py --no-tts        # replies on the dashboard only
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
import uuid
from pathlib import Path

import numpy as np
import websockets

from stress import config as C
from stress.hub import DeviceHub
from stress.intent import match as match_intent
from stress.measurement import MeasurementManager

TOOLS = Path(__file__).resolve().parent
STT_MODEL = TOOLS / "quantized_26_08_21"
TTS_MODEL = TOOLS / "TTS-model" / "en_US-lessac-medium.onnx"
MIN_SECONDS = 0.25


class EventBus:
    """Fan-out to dashboard clients. Never blocks the producer."""

    def __init__(self):
        self.clients: set[asyncio.Queue] = set()
        self.log: list[dict] = []

    def emit(self, kind: str, payload: dict):
        msg = {"type": kind, "t": time.time(), **payload}
        if kind in ("log", "transcript", "reply", "result", "link", "voice"):
            self.log.append(msg)
            self.log = self.log[-200:]
        data = json.dumps(msg, default=_json_default)
        for q in list(self.clients):
            if q.qsize() < 500:
                q.put_nowait(data)

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self.clients.add(q)
        return q

    def unsubscribe(self, q):
        self.clients.discard(q)


def _json_default(o):
    if isinstance(o, (np.floating,)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    return str(o)


# ---------------------------------------------------------------------------
class StressSystem:
    def __init__(self, args):
        self.args = args
        self.bus = EventBus()
        self.hub = DeviceHub(self.bus.emit)
        self.esp32_ws = None
        self.components = {"stt": "off", "llm": "off", "tts": "off", "model": "off"}
        self.stt = self.agent = self.tts = None
        self.model = self._load_model()
        self.mm = MeasurementManager(self.hub, self.bus.emit, self.send_esp32, self.model)
        self.speaking = False
        self.thread_id = str(uuid.uuid4())

    # --------------------------------------------------------------- startup
    def _load_model(self):
        if not C.MODEL_PATH.exists():
            print(f"[model] {C.MODEL_PATH} not found - run tools/ml/train.py (see tools/ml/README.md). "
                  "Measurements will show signals and HR/HRV but no stress prediction.")
            self.components["model"] = "missing"
            return None
        try:
            from ml.predict import StressModel
            m = StressModel(C.MODEL_PATH)
            self.components["model"] = "ok"
            print(f"[model] loaded {C.MODEL_PATH.name}: {m.info()['models']}")
            return m
        except Exception as e:
            print(f"[model] failed to load: {e!r}")
            self.components["model"] = "error"
            return None

    async def init_voice(self):
        if self.args.no_voice:
            return
        import voice_agent_server as vas
        try:
            self.stt = await asyncio.to_thread(vas.MoonshineStreamSTT, str(STT_MODEL))
            self.components["stt"] = "ok"
        except Exception as e:
            print(f"[voice] STT unavailable: {e!r}")
            self.components["stt"] = "error"
        if not self.args.no_tts:
            try:
                self.tts = await asyncio.to_thread(vas.PiperTTS, str(TTS_MODEL))
                self.components["tts"] = "ok"
            except Exception as e:
                print(f"[voice] TTS unavailable: {e!r}")
                self.components["tts"] = "error"
        if not self.args.no_llm:
            try:
                self.agent = vas.LangGraphAgent({})
                await self.agent.init()
                self.components["llm"] = "ok"
            except Exception as e:
                print(f"[voice] LLM agent unavailable: {e!r}")
                self.agent = None
                self.components["llm"] = "error"

    # ------------------------------------------------------------ esp32 link
    async def send_esp32(self, msg: dict) -> bool:
        ws = self.esp32_ws
        if ws is None:
            return False
        try:
            await ws.send(json.dumps(msg))
            return True
        except websockets.ConnectionClosed:
            return False

    async def speak(self, text: str):
        """Dashboard always; laptop speaker if TTS works (ESP32 mic muted meanwhile)."""
        if not text:
            return
        self.bus.emit("reply", {"text": text})
        if self.tts is None:
            return
        self.speaking = True
        await self.send_esp32({"type": "mute"})
        try:
            await asyncio.wait_for(asyncio.to_thread(self.tts.speak, text), timeout=45)
        except Exception as e:
            print(f"[tts] {e!r}")
        finally:
            self.speaking = False
            await self.send_esp32({"type": "unmute"})

    def _on_esp32_text(self, data: dict):
        kind = data.get("type")
        if kind == "status":
            self.hub.esp32.touch(data.get("ip"))
            self.hub.esp32.rssi = data.get("rssi")
            peer = data.pop("peer", {}) or {}
            self.hub.esp32.info.update({k: data.get(k) for k in (
                "uptime", "heap", "mic_ok", "mic_level", "speech", "utterances", "mpu_ok",
                "acc", "measuring", "motion_samples")})
            self.hub.esp32.info["peer"] = peer
            # Laptop not receiving the ESP8266 broadcast (firewall/AP isolation)?
            # Fall back to what the ESP32 hears from it.
            st = self.hub.esp8266
            if peer.get("online") and time.time() - st.last_seen > 3:
                st.touch(peer.get("ip"))
                st.rssi = peer.get("rssi")
                st.info.update({"collecting": peer.get("collecting"), "ppg_raw": peer.get("ppg"),
                                "gsr_raw": peer.get("gsr"), "ads_ok": peer.get("ads"),
                                "via": "esp32"})
            self.bus.emit("audio", {"level": data.get("mic_level", 0), "speech": data.get("speech", 0)})
        elif kind == "peer_event":
            ev, mid = data.get("event"), data.get("id")
            if ev == "ack" and mid in self.hub.acks:
                self.hub.acks[mid].set()
            elif ev == "no_ack":
                self.mm.no_ack_from_esp32.set()
            info = {k: v for k, v in data.items() if k != "type"}
            self.bus.emit("link", {"path": "esp32->esp8266" if ev in ("ack", "no_ack") else "esp32",
                                   **info})
        elif kind == "hello":
            self.bus.emit("log", {"msg": f"ESP32 hello: {data}"})

    async def esp32_handler(self, ws):
        print(f"[+] ESP32 connected: {ws.remote_address}")
        if self.esp32_ws is not None:
            print("    (replacing previous ESP32 connection)")
        self.esp32_ws = ws
        self.hub.esp32.touch(ws.remote_address[0])
        self.bus.emit("log", {"msg": f"ESP32 connected from {ws.remote_address[0]}"})
        queue: asyncio.Queue = asyncio.Queue()
        worker = asyncio.create_task(self._utterance_worker(queue))
        current = None
        last_level = 0.0
        try:
            async for msg in ws:
                if isinstance(msg, (bytes, bytearray)):
                    if current is not None:
                        current["pcm"].extend(msg)
                        now = time.monotonic()
                        if now - last_level > 0.1:
                            last_level = now
                            a = np.frombuffer(bytes(msg[: len(msg) // 2 * 2]), dtype=np.int16)
                            rms = float(np.sqrt(np.mean((a / 32768.0) ** 2))) if len(a) else 0.0
                            self.bus.emit("audio", {"level": rms, "speech": 1})
                    continue
                data = json.loads(msg)
                kind = data.get("type")
                if kind == "speech_start":
                    current = {"id": data["session_id"], "sr": data.get("sample_rate", 16000),
                               "pcm": bytearray()}
                    self.bus.emit("voice", {"event": "speech_start"})
                elif kind == "speech_end" and current and current["id"] == data.get("session_id"):
                    utt, current = current, None
                    secs = len(utt["pcm"]) / 2 / utt["sr"]
                    self.bus.emit("voice", {"event": "speech_end", "seconds": round(secs, 2)})
                    if secs >= MIN_SECONDS:
                        await queue.put(utt)
                else:
                    self._on_esp32_text(data)
        except websockets.ConnectionClosed:
            pass
        finally:
            await queue.put(None)
            worker.cancel()
            if self.esp32_ws is ws:
                self.esp32_ws = None
            self.hub.esp32.online = False
            self.hub.esp32.last_seen = 0
            print("[-] ESP32 disconnected")
            self.bus.emit("log", {"msg": "ESP32 disconnected"})

    async def _utterance_worker(self, queue):
        import voice_agent_server as vas
        while True:
            utt = await queue.get()
            if utt is None:
                return
            if self.stt is None:
                self.bus.emit("log", {"msg": "utterance received but STT is offline"})
                continue
            try:
                u = vas.Utterance(utt["id"], utt["sr"], utt["pcm"])
                t0 = time.perf_counter()
                text = await asyncio.to_thread(self.stt.transcribe, u)
                self.bus.emit("transcript", {"text": text, "stt_ms": round((time.perf_counter() - t0) * 1000)})
                if text:
                    await self.handle_text(text, source="voice")
            except Exception as e:
                print(f"[voice] pipeline error: {e!r}")

    # ------------------------------------------------------------- commands
    async def handle_text(self, text: str, source: str = "voice"):
        intent = match_intent(text)
        self.bus.emit("voice", {"event": "intent", "intent": intent, "text": text})
        if intent in ("measure", "calibrate", "preview"):
            await self.start_measurement(intent, source)
        elif intent == "stop":
            if self.mm.busy:
                self.mm.stop()
            else:
                await self.speak("Nothing is being measured right now.")
        elif self.mm.busy:
            self.bus.emit("log", {"msg": f"ignored during measurement: {text!r}"})
        elif self.agent is not None:
            reply = await self.agent.respond(text, self.thread_id)
            await self.speak(reply)
        else:
            await self.speak("Say: measure my stress level.")

    async def start_measurement(self, kind: str, source: str) -> dict:
        r = self.mm.start(kind, source)
        if not r["ok"]:
            await self.speak(f"I can't start that: {r['reason']}.")
            return r
        intro = {
            "measure": "Starting the stress measurement. Please sit still and breathe normally for one minute.",
            "calibrate": "Calibrating your relaxed baseline. Sit comfortably and relax for three minutes.",
            "preview": "Checking your signals for thirty seconds.",
        }[kind]
        asyncio.create_task(self.speak(intro))
        asyncio.create_task(self._announce_result())
        return r

    async def _announce_result(self):
        res = await self.mm.wait()
        if res:
            await self.speak(res.get("speech") or res.get("reason", ""))

    # -------------------------------------------------------------- snapshot
    def snapshot(self) -> dict:
        return {
            "type": "snapshot", "t": time.time(),
            "devices": {"esp32": self.hub.esp32.to_dict(4.0),
                        "esp8266": self.hub.esp8266.to_dict(4.0)},
            "esp32_ws": self.esp32_ws is not None,
            "components": self.components,
            "speaking": self.speaking,
            "measurement": self.mm.status(),
            "config": {"measure_s": C.MEASURE_S, "calibrate_s": C.CALIBRATE_S,
                       "fs_ppg": C.FS_PPG, "fs_acc": C.FS_ACC},
        }

    async def snapshot_loop(self):
        while True:
            self.bus.emit("snapshot", {k: v for k, v in self.snapshot().items() if k not in ("type", "t")})
            await asyncio.sleep(1.0)


# ---------------------------------------------------------------------------
def build_app(sysm: StressSystem):
    from starlette.applications import Starlette
    from starlette.responses import FileResponse, JSONResponse
    from starlette.routing import Mount, Route, WebSocketRoute
    from starlette.staticfiles import StaticFiles
    from starlette.websockets import WebSocketDisconnect

    async def index(_):
        return FileResponse(C.DASHBOARD_DIR / "index.html")

    async def api_status(_):
        return JSONResponse(json.loads(json.dumps(sysm.snapshot(), default=_json_default)))

    async def api_measure(request):
        body = await request.json() if await request.body() else {}
        r = await sysm.start_measurement(body.get("kind", "measure"), "dashboard")
        return JSONResponse(r)

    async def api_stop(_):
        sysm.mm.stop()
        return JSONResponse({"ok": True})

    async def api_gsr_cal(_):
        return JSONResponse(sysm.mm.set_gsr_calibration())

    async def api_say(request):
        """Type a sentence as if it was spoken (testing without the microphone)."""
        body = await request.json()
        text = body.get("text", "")
        sysm.bus.emit("transcript", {"text": text, "typed": True})
        asyncio.create_task(sysm.handle_text(text, source="typed"))
        return JSONResponse({"ok": True, "intent": match_intent(text)})

    async def api_session(request):
        sid = request.path_params["sid"]
        files = list((C.DATA_DIR / "sessions").glob(f"*_{sid}.json"))
        if not files:
            return JSONResponse({"ok": False}, status_code=404)
        return JSONResponse(json.loads(files[0].read_text()))

    async def ws_endpoint(websocket):
        await websocket.accept()
        q = sysm.bus.subscribe()
        try:
            await websocket.send_text(json.dumps(sysm.snapshot(), default=_json_default))
            await websocket.send_text(json.dumps({"type": "backlog", "items": sysm.bus.log[-60:]},
                                                 default=_json_default))
            while True:
                await websocket.send_text(await q.get())
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            sysm.bus.unsubscribe(q)

    return Starlette(routes=[
        Route("/", index),
        Route("/api/status", api_status),
        Route("/api/measure", api_measure, methods=["POST"]),
        Route("/api/stop", api_stop, methods=["POST"]),
        Route("/api/gsr_calibrate", api_gsr_cal, methods=["POST"]),
        Route("/api/say", api_say, methods=["POST"]),
        Route("/api/session/{sid}", api_session),
        WebSocketRoute("/ws", ws_endpoint),
        Mount("/static", StaticFiles(directory=str(C.DASHBOARD_DIR)), name="static"),
    ])


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-voice", action="store_true", help="no STT/TTS/LLM")
    ap.add_argument("--no-llm", action="store_true", help="voice commands only, no chat agent")
    ap.add_argument("--no-tts", action="store_true", help="replies only on the dashboard (no speaker)")
    ap.add_argument("--http-port", type=int, default=C.HTTP_PORT)
    args = ap.parse_args()

    import uvicorn
    sysm = StressSystem(args)
    await sysm.hub.start()
    await sysm.init_voice()
    print(f"components: {sysm.components}")

    server = uvicorn.Server(uvicorn.Config(build_app(sysm), host=C.HTTP_HOST, port=args.http_port,
                                           log_level="warning"))
    async with websockets.serve(sysm.esp32_handler, C.WS_HOST, C.WS_PORT, max_size=None):
        print(f"ESP32 WebSocket   ws://{C.WS_HOST}:{C.WS_PORT}/audio")
        print(f"UDP               vitals :{C.PORT_VITALS}  motion :{C.PORT_MOTION}  status :{C.PORT_STATUS}")
        print(f"Dashboard         http://localhost:{args.http_port}")
        asyncio.create_task(sysm.snapshot_loop())
        await server.serve()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
