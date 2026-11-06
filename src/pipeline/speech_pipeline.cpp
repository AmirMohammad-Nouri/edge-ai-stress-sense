#include "speech_pipeline.h"
#include "../protocol/websocket.h"
#include "../status.h"

#include <Arduino.h>
#include <esp_system.h>
#include <stdio.h>

const char* SpeechPipeline::stateName() const {
    switch (state_) {
        case SpeechState::IDLE:      return "IDLE";
        case SpeechState::SPEAKING:  return "SPEAKING";
        case SpeechState::MAYBE_END: return "MAYBE_END";
    }
    return "?";
}

void SpeechPipeline::emit(const int16_t* frame) {
    if (!net::sendAudio(frame)) {
        overflow_ = true;            // WiFi stalled: queue is full
    }
    utterFrames_++;
}

void SpeechPipeline::beginUtterance() {
    snprintf(session_, sizeof(session_), "%08lx%04x",
             (unsigned long)esp_random(), (unsigned)(++sessionCtr_));

    if (!net::sendStart(session_)) {
        // Queue full; keep the ring and retry on the next frame.
        Serial.println("[pipe] cannot enqueue speech_start, retrying");
        return;
    }

    const size_t pre = ring_.count();
    state_         = SpeechState::SPEAKING;
    silenceFrames_ = 0;
    utterFrames_   = 0;
    overflow_      = false;

    // Pre-roll (already contains the debounce/trigger frames, oldest first).
    for (size_t i = 0; i < pre; ++i) emit(ring_.at(i));
    ring_.clear();

    status::utterances++;
    Serial.printf("[pipe] speech_start id=%s (pre-roll %u frames)\n", session_, (unsigned)pre);
}

void SpeechPipeline::endUtterance(const char* reason) {
    net::sendEnd(session_);
    Serial.printf("[pipe] speech_end   id=%s (%d ms, %s)\n",
                  session_, utterFrames_ * FRAME_MS, reason);
    state_         = SpeechState::IDLE;
    silenceFrames_ = 0;
    speechRun_     = 0;
    utterFrames_   = 0;
    overflow_      = false;
    ring_.clear();
}

void SpeechPipeline::abortUtterance(const char* reason) {
    Serial.printf("[pipe] utterance %s aborted: %s\n", session_, reason);
    state_         = SpeechState::IDLE;
    silenceFrames_ = 0;
    speechRun_     = 0;
    utterFrames_   = 0;
    overflow_      = false;
    ring_.clear();
}

void SpeechPipeline::processFrame(const int16_t* frame) {
    // While the server is speaking (TTS), don't listen at all: an unmuted
    // mic would capture the agent's own voice from the speaker and send it
    // right back as a new "utterance", causing the agent to talk to itself.
    const bool muted = net::isMuted();
    if (muted) {
        if (state_ != SpeechState::IDLE) abortUtterance("muted (agent speaking)");
        wasMuted_ = true;
        return;                      // skip VAD, ring, everything
    }
    if (wasMuted_) {
        // Just unmuted: drop any pre-roll/debounce state from before the
        // mute window so a false start can't fire immediately. Do NOT
        // reset the VAD itself -- that would also wipe its calibrated
        // noise floor and force 50 frames of recalibration, during which
        // real speech would be misread as silence.
        wasMuted_ = false;
        ring_.clear();
        speechRun_ = 0;
    }

    const bool speech = vad_.process(frame, FRAME_SAMPLES);
    status::reportLevel(vad_.level());

#if DEBUG_VAD_LEVELS
    if (++dbgCounter_ >= (1000 / FRAME_MS)) {
        dbgCounter_ = 0;
        char b[112];
        vad_.describe(b, sizeof(b));
        Serial.printf("[vad] %s | %s\n", b, stateName());
    }
#endif

    if (state_ != SpeechState::IDLE && !net::isConnected()) {
        abortUtterance("websocket lost");
    }

    switch (state_) {
        case SpeechState::IDLE:
            // Always keep the newest frames; the ring IS the pre-roll.
            ring_.push(frame);
            speechRun_ = speech ? speechRun_ + 1 : 0;
            if (speechRun_ >= START_CONFIRM_FRAMES && net::isConnected()) {
                beginUtterance();
            }
            break;

        case SpeechState::SPEAKING:
            emit(frame);
            if (!speech) {
                silenceFrames_ = 1;
                state_ = SpeechState::MAYBE_END;
            }
            break;

        case SpeechState::MAYBE_END:
            emit(frame);            // keep the pause: speaker may continue
            if (speech) {
                silenceFrames_ = 0;
                state_ = SpeechState::SPEAKING;
            } else if (++silenceFrames_ >= END_SILENCE_FRAMES) {
                endUtterance("silence");
            }
            break;
    }

    status::speechState = (uint8_t)state_;

    if (state_ != SpeechState::IDLE) {
        if (overflow_) {
            endUtterance("send queue overflow");
        } else if (utterFrames_ >= MAX_UTTERANCE_FRAMES) {
            endUtterance("max length");
        }
    }
}