#include "vad.h"
#include "../config.h"
#include <math.h>
#include <stdio.h>

static inline float maxf(float a, float b) { return a > b ? a : b; }

void EnergyVad::reset() {
    rms_ = 0.0f;
    floor_ = 0.0f;
    calib_ = 0;
    active_ = false;
}

float EnergyVad::startThresh() const { return maxf(floor_ * VAD_START_RATIO, VAD_MIN_START_RMS); }
float EnergyVad::stopThresh()  const { return maxf(floor_ * VAD_STOP_RATIO,  VAD_MIN_STOP_RMS); }

bool EnergyVad::process(const int16_t* s, size_t n) {
    float sum = 0.0f;
    for (size_t i = 0; i < n; ++i) {
        float v = s[i] * (1.0f / 32768.0f);
        sum += v * v;
    }
    rms_ = sqrtf(sum / (float)n);

    // Calibration: running mean of the first ~1 s
    if (calib_ < VAD_CALIBRATION_FRAMES) {
        floor_ += (rms_ - floor_) / (float)(calib_ + 1);
        calib_++;
        return false;
    }

    active_ = active_ ? (rms_ > stopThresh()) : (rms_ > startThresh());

    // Learn the noise floor only from non-speech frames
    if (!active_) {
        float a = (rms_ > floor_) ? VAD_FLOOR_RISE : VAD_FLOOR_FALL;
        floor_ = (1.0f - a) * floor_ + a * rms_;
        if (floor_ < 1e-4f) floor_ = 1e-4f;
    }
    return active_;
}

void EnergyVad::describe(char* buf, size_t n) const {
    snprintf(buf, n, "rms=%.4f floor=%.4f start>%.4f stop<%.4f%s",
             rms_, floor_, startThresh(), stopThresh(),
             calib_ < VAD_CALIBRATION_FRAMES ? " (calibrating)" : "");
}
