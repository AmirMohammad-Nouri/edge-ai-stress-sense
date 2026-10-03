#pragma once
#include <string.h>
#include "../config.h"

// Fixed-size ring of whole frames. Used for the pre-roll: while IDLE every
// frame is pushed here; when speech is confirmed the whole ring is flushed
// to the network (oldest first) and cleared.
class FrameRing {
public:
    void push(const int16_t* frame) {
        memcpy(buf_[head_], frame, FRAME_BYTES);
        head_ = (head_ + 1) % RING_FRAMES;
        if (count_ < RING_FRAMES) count_++;
    }

    size_t count() const { return count_; }

    // i = 0 is the oldest frame
    const int16_t* at(size_t i) const {
        size_t start = (head_ + RING_FRAMES - count_) % RING_FRAMES;
        return buf_[(start + i) % RING_FRAMES];
    }

    void clear() { head_ = 0; count_ = 0; }

private:
    int16_t buf_[RING_FRAMES][FRAME_SAMPLES];
    size_t  head_  = 0;
    size_t  count_ = 0;
};
