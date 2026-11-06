#pragma once
#include <stddef.h>

// Measurement coordinator (runs in its own task on the ESP32).
//
//   laptop --WS {"type":"measure_start","id":..,"duration_ms":..}--> ESP32
//   ESP32  --UDP "START,id,dur,laptop_ip,port"--> ESP8266   (retried until "ACK,id")
//   ESP32  --UDP MPU6050 packets--> laptop:4213     ESP8266 --UDP PPG/GSR--> laptop:4211
//   ESP32  --WS {"type":"peer_event",...} / {"type":"status",...}--> laptop
//
// It also discovers the ESP8266 from its broadcast heartbeats and reports
// both boards' health to the laptop once per second (dashboard).
namespace coord {

bool start();                                        // init MPU + UDP, spawn task
void onServerCommand(const char* json, size_t len);  // called by the WS network task

}  // namespace coord
