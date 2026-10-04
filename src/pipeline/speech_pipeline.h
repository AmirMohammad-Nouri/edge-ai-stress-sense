#pragma once
#include "../audio/audio_buffer.h"
#include "../vad/vad.h"
#include "../config.h"

enum class SpeechState : uint8_t { IDLE, SPEAKING, MAYBE_END };

// IDLE --(N consecutive speech frames)--> SPEAKING
// SPEAKING --(silence)--> MAYBE_END --(speech)--> SPEAKING
// MAYBE_END --(silence >= END_SILENCE_FRAMES)--> IDLE   (speech_end)
class SpeechPipeline {
public:
    explicit SpeechPipeline(IVad& vad) : vad_(vad) {}

    // Feed exactly one 20 ms frame (FRAME_SAMPLES x int16).
    void processFrame(const int16_t* frame);

    SpeechState state() const { return state_; }

private:
    void beginUtterance();
    void endUtterance(const char* reason);
    void abortUtterance(const char* reason);
    void emit(const int16_t* frame);
    const char* stateName() const;

    IVad&       vad_;
    FrameRing   ring_;
    SpeechState state_        = SpeechState::IDLE;
    int         speechRun_    = 0;    // consecutive speech frames while IDLE
    int         silenceFrames_= 0;
    int         utterFrames_  = 0;
    bool        overflow_     = false;
    uint16_t    sessionCtr_   = 0;
    char        session_[SESSION_ID_LEN] = {0};
    int         dbgCounter_   = 0;
    bool        wasMuted_     = false;
};