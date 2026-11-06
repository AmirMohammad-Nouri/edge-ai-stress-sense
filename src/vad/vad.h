#pragma once
#include <stddef.h>
#include <stdint.h>

// Swap implementations (energy / WebRTC / neural) without touching the pipeline.
class IVad {
public:
    virtual ~IVad() {}
    // Returns true if this frame contains speech.
    virtual bool process(const int16_t* samples, size_t count) = 0;
    virtual void reset() = 0;
    // Optional: human-readable levels for the serial monitor.
    virtual void describe(char* buf, size_t n) const { if (n) buf[0] = 0; }
    // RMS of the last frame, normalised 0..1 (for the dashboard level meter).
    virtual float level() const { return 0.0f; }
};

// Energy VAD with:
//   - 1 s calibration at boot (stay quiet!)
//   - adaptive noise floor (only updated while NOT in speech)
//   - hysteresis: higher threshold to start, lower to keep going
class EnergyVad : public IVad {
public:
    EnergyVad() { reset(); }
    bool process(const int16_t* samples, size_t count) override;
    void reset() override;
    void describe(char* buf, size_t n) const override;
    float level() const override { return rms_; }

private:
    float startThresh() const;
    float stopThresh()  const;

    float rms_    = 0.0f;
    float floor_  = 0.0f;
    int   calib_  = 0;
    bool  active_ = false;
};
