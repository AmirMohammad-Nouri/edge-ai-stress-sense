#pragma once
#include <stddef.h>
#include <stdint.h>

// Thin, thread-safe facade. The audio task calls send*(); a dedicated network
// task owns the WebSocket and drains a queue, so a WiFi stall can never block
// (and overrun) the I2S reader.
namespace net {

bool start();               // create queue + network task
bool isConnected();

// True while the server is speaking (TTS playback). The audio pipeline
// should not start or continue an utterance while this is true, so the
// device doesn't capture and re-transcribe its own voice from the
// server's speaker (acoustic feedback loop).
bool isMuted();

bool sendStart(const char* sessionId);
bool sendAudio(const int16_t* frame);        // exactly FRAME_SAMPLES samples
bool sendEnd(const char* sessionId);

}  // namespace net