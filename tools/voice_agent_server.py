#!/usr/bin/env python3
"""
ESP32 voice agent server: WebSocket in -> STT -> LangGraph agent (+ MCP
tools) -> Piper TTS -> playback.

Pipeline, per connected device (one queue + one worker, in order,
never blocking the WebSocket receive loop):

    binary PCM frames --> Utterance
                              │
                   MoonshineStreamSTT.transcribe(utt)   -> text
                              │
                   Agent.respond(text, thread_id)       -> reply text
                              │
                   mute -> PiperTTS.speak(reply) -> unmute

    pip install moonshine-voice langgraph langchain-mcp-adapters \
                langchain-ollama piper-tts sounddevice numpy websockets
    (also: `ollama pull qwen3:0.6b` and have `ollama serve` running)
"""
import asyncio
import json
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import websockets

HOST, PORT = "0.0.0.0", 8765
MIN_SECONDS = 0.25

# MCP servers to pull tools from. Empty list = agent runs with no tools.
# Each entry follows langchain-mcp-adapters' MultiServerMCPClient config.
MCP_SERVERS = {
    # "vitals": {"transport": "stdio", "command": "python", "args": ["mcp_servers/vitals.py"]},
}

# Strips emoji / pictographs so the TTS voice never has to "read" one aloud
# (e.g. Piper narrating a smiley as "smiling face with smiling eyes").
_EMOJI_RE = re.compile(
    "[" "\U0001F300-\U0001FAFF" "\U00002600-\U000027BF"
    "\U0001F1E6-\U0001F1FF" "\U00002190-\U000021FF" "\U00002B00-\U00002BFF"
    "️" "]+", flags=re.UNICODE,
)


def clean_for_speech(text: str) -> str:
    return _EMOJI_RE.sub("", text).strip()


NO_EMOJI_SYSTEM_PROMPT = (
    "You are a concise voice assistant. Your replies are read aloud by a "
    "text-to-speech engine, so: never use emojis, emoticons, or symbols; "
    "never use markdown; write plain spoken sentences only."
)


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
        n = len(self.pcm) // 2 * 2
        return np.frombuffer(self.pcm[:n], dtype=np.int16).astype(np.float32) / 32768.0


# --------------------------------------------------------------------------
# STT: moonshine_voice.Transcriber fed from our already-segmented utterance.
# Using the low-level Transcriber (not MicTranscriber) because audio arrives
# over the network, already VAD-segmented by the ESP32 -- there is no local
# mic to capture from.
# --------------------------------------------------------------------------
class MoonshineStreamSTT:
    def __init__(self, model_path: str):
        from moonshine_voice import Transcriber, ModelArch

        self._transcriber = Transcriber(
            model_path=model_path,
            model_arch=ModelArch.TINY_STREAMING,
            update_interval=0.5,
        )

    def transcribe(self, utt: Utterance) -> str:
        """Blocking. Run via asyncio.to_thread() from the async pipeline."""
        stream = self._transcriber.create_stream()

        transcripts = []

        def on_transcript(event):
            transcripts.append(str(event))

        stream.add_listener(on_transcript)
        stream.start()

        try:
            chunk_samples = int(utt.sample_rate * 0.1)
            audio = utt.audio()

            for i in range(0, len(audio), chunk_samples):
                chunk = audio[i:i + chunk_samples]
                stream.add_audio(chunk.tolist(), utt.sample_rate)

            result = stream.update_transcription()

            if hasattr(result, "text"):
                return result.text.strip()
            return str(result).strip()

        finally:
            stream.stop()
            stream.close()


# --------------------------------------------------------------------------
# Agent: LangGraph prebuilt ReAct agent, tools pulled from MCP servers.
# One thread_id per *device connection* (not per utterance) so the agent
# keeps conversational memory across turns from the same device.
# --------------------------------------------------------------------------
class LangGraphAgent:
    def __init__(self, mcp_servers: dict):
        self._mcp_servers = mcp_servers
        self._graph = None  # built lazily in async init()

    async def init(self):
        from langchain_mcp_adapters.client import MultiServerMCPClient
        from langgraph.prebuilt import create_react_agent
        from langgraph.checkpoint.memory import MemorySaver
        from langchain_ollama import ChatOllama   # local, via `ollama serve`

        tools = []
        if self._mcp_servers:
            client = MultiServerMCPClient(self._mcp_servers)
            tools = await client.get_tools()

        # Requires: ollama pull qwen3:1.7b   (and `ollama serve` running)
        llm = ChatOllama(model="qwen3:1.7b")
        self._graph = create_react_agent(
            llm, tools, prompt=NO_EMOJI_SYSTEM_PROMPT, checkpointer=MemorySaver()
        )

    async def respond(self, text: str, thread_id: str) -> str:
        result = await self._graph.ainvoke(
            {"messages": [{"role": "user", "content": text}]},
            config={"configurable": {"thread_id": thread_id}},
        )
        return clean_for_speech(result["messages"][-1].content)


# --------------------------------------------------------------------------
# TTS: Piper -> wav bytes -> playback. Runs off the event loop (blocking).
# --------------------------------------------------------------------------
class PiperTTS:
    def __init__(self, model_path: str = "en_US-lessac-medium.onnx", use_cuda: bool = False):
        from piper import PiperVoice
        self._voice = PiperVoice.load(model_path, use_cuda=use_cuda)

    def speak(self, text: str) -> None:
        """Blocking: synthesize then play. Run via asyncio.to_thread()."""
        import io
        import wave
        import sounddevice as sd

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wav_file:
            self._voice.synthesize_wav(text, wav_file)
        buf.seek(0)
        with wave.open(buf, "rb") as wav_file:
            rate = wav_file.getframerate()
            frames = wav_file.readframes(wav_file.getnframes())
            audio = np.frombuffer(frames, dtype=np.int16)
        sd.play(audio, rate)
        sd.wait()


# --------------------------------------------------------------------------
class VoicePipeline:
    def __init__(self, stt: MoonshineStreamSTT, agent: LangGraphAgent, tts: PiperTTS):
        self.stt, self.agent, self.tts = stt, agent, tts

    async def __call__(self, utt: Utterance, thread_id: str, ws) -> dict:
        t0 = time.perf_counter()
        text = await asyncio.to_thread(self.stt.transcribe, utt)
        t1 = time.perf_counter()
        if not text:
            return {"text": "", "reply": "", "stt_ms": round((t1 - t0) * 1000)}

        reply = await self.agent.respond(text, thread_id)
        t2 = time.perf_counter()

        # Mute the device's mic while the reply plays, so it doesn't hear
        # (and transcribe) its own voice -- otherwise the agent ends up
        # talking to itself in a feedback loop. speak() blocks until
        # playback ends, so unmute only fires once the speaker has
        # actually gone quiet. The timeout unmutes anyway if the "mute"
        # message is ever lost or the connection drops, so the mic can
        # never get stuck off.
        await ws.send(json.dumps({"type": "mute"}))
        try:
            await asyncio.wait_for(asyncio.to_thread(self.tts.speak, reply), timeout=30)
        finally:
            try:
                await ws.send(json.dumps({"type": "unmute"}))
            except websockets.ConnectionClosed:
                pass
        t3 = time.perf_counter()

        return {
            "text": text, "reply": reply,
            "stt_ms": round((t1 - t0) * 1000),
            "agent_ms": round((t2 - t1) * 1000),
            "tts_ms": round((t3 - t2) * 1000),
        }


# --------------------------------------------------------------------------
def make_handler(pipeline: VoicePipeline):
    async def handler(ws):
        thread_id = str(uuid.uuid4())     # one conversation per connection
        print(f"[+] device connected: {ws.remote_address} (thread {thread_id[:8]})")
        queue: asyncio.Queue = asyncio.Queue()

        async def worker():
            while True:
                utt = await queue.get()
                if utt is None:
                    return
                try:
                    r = await pipeline(utt, thread_id, ws)
                    if r["text"]:
                        print(f"    You: {r['text']!r}  (stt {r['stt_ms']}ms, "
                              f"agent {r['agent_ms']}ms, tts {r['tts_ms']}ms)")
                        print(f"    Agent: {r['reply']!r}")
                except Exception as e:
                    print(f"    pipeline error: {e!r}")

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
                    if utt.seconds >= MIN_SECONDS:
                        await queue.put(utt)
                elif kind == "hello":
                    print(f"    hello: {data}")
        except websockets.ConnectionClosed:
            pass
        finally:
            if current is not None:
                print(f"    dropped partial utterance {current.session_id}")
            await queue.put(None)
            await worker_task
            print("[-] device disconnected")

    return handler


async def main():
    stt = MoonshineStreamSTT(
        "/home/arshix/projects/wireless_project/esp32_voice/tools/quantized_26_08_21"
    )

    agent = LangGraphAgent(MCP_SERVERS)
    await agent.init()

    tts = PiperTTS("/home/arshix/projects/wireless_project/esp32_voice/tools/TTS-model/en_US-lessac-medium.onnx")
    pipeline = VoicePipeline(stt, agent, tts)

    async with websockets.serve(
        make_handler(pipeline),
        HOST,
        PORT,
        max_size=None
    ):
        print(f"listening on ws://{HOST}:{PORT}")
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())