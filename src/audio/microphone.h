#pragma once
#include <stddef.h>
#include <stdint.h>
#include "../config.h"

// Reads one 20 ms frame (320 x int16, 16 kHz, mono) from an I2S MEMS mic.
class Microphone {
public:
    bool begin();
    // Blocks until a full frame is available. Returns false on I2S error/timeout.
    bool readFrame(int16_t* out);

private:
    int32_t raw_[FRAME_SAMPLES];
    float   dcPrevIn_  = 0.0f;
    float   dcPrevOut_ = 0.0f;
};
