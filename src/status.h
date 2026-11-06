#pragma once
#include <atomic>
#include <stdint.h>

// Lock-free values written by one task and read by the coordinator, which
// reports them to the laptop once per second (dashboard). Defined in status.cpp.
namespace status {

extern std::atomic<float>    micLevelPeak;   // max frame RMS since last report (0..1)
extern std::atomic<uint8_t>  speechState;    // 0 idle, 1 speaking, 2 maybe_end
extern std::atomic<bool>     micOk;
extern std::atomic<uint32_t> utterances;

void reportLevel(float rms);

}  // namespace status
