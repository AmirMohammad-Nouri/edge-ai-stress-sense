#pragma once
#include <stddef.h>
#include <stdint.h>

// Thin, thread-safe facade. The audio task calls send*(); a dedicated network
// task owns the WebSocket and drains a queue, so a WiFi stall can never block
// (and overrun) the I2S reader.
namespace net {

bool start();               // create queue + network task
bool isConnected();

bool sendStart(const char* sessionId);
bool sendAudio(const int16_t* frame);        // exactly FRAME_SAMPLES samples
bool sendEnd(const char* sessionId);

}  // namespace net
