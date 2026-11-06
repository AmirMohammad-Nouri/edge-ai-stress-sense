#include "status.h"

namespace status {

std::atomic<float>    micLevelPeak{0.0f};
std::atomic<uint8_t>  speechState{0};
std::atomic<bool>     micOk{false};
std::atomic<uint32_t> utterances{0};

void reportLevel(float rms) {
    float cur = micLevelPeak.load(std::memory_order_relaxed);
    while (rms > cur && !micLevelPeak.compare_exchange_weak(cur, rms)) {}
}

}  // namespace status
