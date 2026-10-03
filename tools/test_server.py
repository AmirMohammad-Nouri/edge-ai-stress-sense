#!/usr/bin/env python3
"""
Minimal test server for the ESP32 firmware.
Accepts the speech_start / binary PCM / speech_end protocol and saves each
utterance as a WAV file in ./recordings so you can listen and tune the VAD.

    pip install websockets
    python test_server.py
"""
import asyncio
import json
import time
import wave
from pathlib import Path

import websockets

HOST, PORT = "0.0.0.0", 8765
OUT = Path("recordings")
OUT.mkdir(exist_ok=True)


def save_wav(path: Path, pcm: bytes, rate: int, channels: int) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)          # PCM16
        w.setframerate(rate)
        w.writeframes(pcm)


async def handler(ws):
    print(f"[+] client connected: {ws.remote_address}")
    session = None
    meta = {}
    pcm = bytearray()
    t_start = 0.0

    try:
        async for msg in ws:
            if isinstance(msg, (bytes, bytearray)):
                if session is not None:
                    pcm.extend(msg)
                continue

            data = json.loads(msg)
            kind = data.get("type")

            if kind == "hello":
                print(f"    hello: {data}")

            elif kind == "speech_start":
                session, meta, pcm, t_start = data["session_id"], data, bytearray(), time.time()
                print(f"    speech_start {session}")

            elif kind == "speech_end" and session == data.get("session_id"):
                rate = meta.get("sample_rate", 16000)
                dur = len(pcm) / 2 / rate
                path = OUT / f"{int(time.time())}_{session}.wav"
                save_wav(path, bytes(pcm), rate, meta.get("channels", 1))
                print(f"    speech_end   {session}: {dur:.2f}s audio "
                      f"(took {time.time() - t_start:.2f}s wall) -> {path}")
                # >>> here you would hand bytes(pcm) to Moonshine <<<
                session = None
    except websockets.ConnectionClosed:
        pass
    finally:
        if session is not None:
            print(f"    connection dropped mid-utterance {session}, discarding {len(pcm)} bytes")
        print("[-] client disconnected")


async def main():
    async with websockets.serve(handler, HOST, PORT, max_size=None):
        print(f"listening on ws://{HOST}:{PORT}  (recordings -> {OUT.resolve()})")
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
