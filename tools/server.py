#!/usr/bin/env python3
"""
ESP32 voice server: WebSocket in -> in-memory audio -> STT -> translation.

Audio never touches the disk (unless SAVE_WAV=1, for debugging only):

    binary frames --> bytearray --> numpy float32 [-1, 1] --> STT --> text
                                                                  --> translate

    pip install websockets numpy
    pip install useful-moonshine-onnx      # for the Moonshine adapter
    python server.py                       # SAVE_WAV=1 python server.py  (debug copies)
"""
import asyncio
import json
import os
import threading
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np
import websockets

HOST, PORT = "0.0.0.0", 8765
MIN_SECONDS = 0.25                       # drop clicks / noise bursts
SAVE_WAV = os.environ.get("SAVE_WAV") == "1"
SEND_RESULT_TO_DEVICE = False            # the ESP32 only logs text replies; keep it off


# --------------------------------------------------------------------------
# One utterance = everything between speech_start and speech_end
# --------------------------------------------------------------------------
@dataclass
class Utterance:
    session_id: str
    sample_rate: int = 16000
    pcm: bytearray = field(default_factory=bytearray)

    @property
    def seconds(self) -> float:
        return len(self.pcm) / 2 / self.sample_rate

    def audio(self) -> np.ndarray:
        """float32 in [-1, 1], exactly what Moonshine expects (16 kHz mono)."""
        n = len(self.pcm) // 2 * 2
        return np.frombuffer(self.pcm[:n], dtype=np.int16).astype(np.float32) / 32768.0


# --------------------------------------------------------------------------
# Pluggable stages: anything callable works, swap freely
# --------------------------------------------------------------------------
class MoonshineTranscriber:
    """np.ndarray(float32, 16 kHz) -> str"""

    def __init__(self, model_name: str = "moonshine/tiny"):
        from moonshine_onnx import MoonshineOnnxModel, load_tokenizer
        self.model = MoonshineOnnxModel(model_name=model_name)
        self.tokenizer = load_tokenizer()
        self(np.zeros(16000, dtype=np.float32))          # warm-up (first call is slow)

    def __call__(self, audio: np.ndarray) -> str:
        tokens = self.model.generate(audio[np.newaxis, :].astype(np.float32))
        return self.tokenizer.decode_batch(tokens)[0].strip()


class Translator:
    """str -> str. Replace with your MT model / LLM call."""

    def __init__(self, target_lang: str = "fi"):
        self.target_lang = target_lang

    def __call__(self, text: str) -> str:
        return f"[{self.target_lang}] {text}"            # TODO: real translation


class VoicePipeline:
    def __init__(self, stt: Callable, translate: Callable):
        self.stt, self.translate = stt, translate
        self._lock = threading.Lock()                    # models are not thread-safe

    def __call__(self, utt: Utterance) -> dict:          # runs in a worker thread
        with self._lock:
            t0 = time.perf_counter()
            text = self.stt(utt.audio())
            t1 = time.perf_counter()
            translated = self.translate(text) if text else ""
            t2 = time.perf_counter()
        return {
            "session_id": utt.session_id,
            "audio_s": round(utt.seconds, 2),
            "text": text,
            "translation": translated,
            "stt_ms": round((t1 - t0) * 1000),
            "translate_ms": round((t2 - t1) * 1000),
        }


# --------------------------------------------------------------------------
# WebSocket handling
# --------------------------------------------------------------------------
def save_wav(utt: Utterance) -> None:
    out = Path("recordings")
    out.mkdir(exist_ok=True)
    with wave.open(str(out / f"{int(time.time())}_{utt.session_id}.wav"), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(utt.sample_rate)
        w.writeframes(bytes(utt.pcm))


def make_handler(pipeline: VoicePipeline):
    async def handler(ws):
        print(f"[+] device connected: {ws.remote_address}")
        queue: asyncio.Queue = asyncio.Queue()

        async def worker():
            # One worker per connection => utterances are processed in order,
            # and the receive loop is never blocked by inference.
            while True:
                utt = await queue.get()
                if utt is None:
                    return
                try:
                    result = await asyncio.to_thread(pipeline, utt)
                    print(f"    {result['audio_s']}s | STT {result['stt_ms']} ms | "
                          f"{result['text']!r} -> {result['translation']!r}")
                    if SEND_RESULT_TO_DEVICE:
                        await ws.send(json.dumps({"type": "result", **result}))
                except Exception as e:                   # never let one bad utterance kill the worker
                    print(f"    pipeline error for {utt.session_id}: {e!r}")

        worker_task = asyncio.create_task(worker())
        current: Utterance | None = None

        try:
            async for msg in ws:
                if isinstance(msg, (bytes, bytearray)):
                    if current is not None:
                        current.pcm.extend(msg)
                    continue

                data = json.loads(msg)
                kind = data.get("type")

                if kind == "speech_start":
                    current = Utterance(data["session_id"], data.get("sample_rate", 16000))
                elif kind == "speech_end" and current and current.session_id == data.get("session_id"):
                    utt, current = current, None
                    if utt.seconds < MIN_SECONDS:
                        print(f"    ignored {utt.session_id}: only {utt.seconds:.2f}s")
                        continue
                    if SAVE_WAV:
                        save_wav(utt)
                    await queue.put(utt)
                elif kind == "hello":
                    print(f"    hello: {data}")
        except websockets.ConnectionClosed:
            pass
        finally:
            if current is not None:
                print(f"    dropped partial utterance {current.session_id}")
            await queue.put(None)
            await worker_task                           # finish what was already queued
            print("[-] device disconnected")

    return handler


async def serve(pipeline: VoicePipeline, host=HOST, port=PORT):
    async with websockets.serve(make_handler(pipeline), host, port, max_size=None):
        print(f"listening on ws://{host}:{port}")
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(serve(VoicePipeline(MoonshineTranscriber("moonshine/tiny"), Translator("fi"))))
