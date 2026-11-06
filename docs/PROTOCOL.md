# Wireless protocol

All three devices must be on the **same WiFi network**. The laptop IP is
configured only on the ESP32 (`WS_HOST`). The ESP8266 needs no IPs: it is
discovered from its broadcast heartbeats, and every START command tells it where to send data.

## Ports

| Port | Proto | Direction | Content |
|---|---|---|---|
| 8765 | TCP / WebSocket `/audio` | ESP32 ⇄ laptop | speech audio, ESP32 status, measurement commands |
| 4210 | UDP | → ESP8266 | `START` / `STOP` / `PING` (from the ESP32, or the laptop as fallback) |
| 4211 | UDP | ESP8266 → laptop | PPG + GSR samples |
| 4212 | UDP | ESP8266 → broadcast | heartbeat, `ACK`, `DONE` (both the ESP32 and the laptop listen) |
| 4213 | UDP | ESP32 → laptop | MPU6050 samples |
| 8080 | HTTP | browser → laptop | dashboard |

Open these in the laptop firewall (Ubuntu: `sudo ufw allow 8765/tcp; sudo ufw allow 4211:4213/udp; sudo ufw allow 8080/tcp`).

## Measurement sequence

```
 you: "measure my stress level"
   ESP32 mic ──WS PCM──► laptop: STT → intent = measure
   laptop ──WS {"type":"measure_start","id":"m123","duration_ms":60000}──► ESP32
   ESP32  ──UDP:4210 "START,m123,60000,<laptop_ip>,4211"──► ESP8266   (re-sent every 250 ms, max 6×)
   ESP8266 ──UDP "ACK,m123"──► ESP32 ──WS {"type":"peer_event","event":"ack"}──► laptop
   ESP8266: LED ON, PPG+GSR @64 Hz ──UDP:4211──► laptop
   ESP32:   MPU6050 @32 Hz          ──UDP:4213──► laptop
   ... 60 s ...
   ESP8266: LED OFF ──"DONE,m123,3840"──► ESP32 ──peer_event peer_done──► laptop
   laptop: interpolate lost samples → GSR counts→µS → features → model → dashboard + spoken result
```

**Fallback:** if the ESP32 is offline, or the ESP8266 does not ACK within 2 s,
the laptop sends the same `START` straight to the ESP8266, using the IP from its heartbeat.
The dashboard shows which path was used ("via ESP32 relay" / "direct").

## Packet formats (ASCII, comma-separated)

```
ESP8266 data      P,<id>,<first_sample_index>,<n>,<ppg0>,<gsr0>,...,<ppgN>,<gsrN>      n = 8 (125 ms)
ESP32 motion      A,<id>,<first_sample_index>,<n>,<ax>,<ay>,<az>,<gx>,<gy>,<gz>,...     n = 8 (250 ms), g and deg/s
heartbeat (1 Hz)  HB,esp8266,<rssi>,<collecting>,<uptime_s>,<ppg_raw>,<gsr_raw>,<ads_ok>,<id>,<samples>
replies           ACK,<id>     DONE,<id>,<samples>     PONG,esp8266
commands          START,<id>,<duration_ms>,<laptop_ip>,<port>    STOP,<id>    PING
```

The sample index gives the timing (index / fs), so packet loss shows up as gaps.
The laptop reports loss per measurement and interpolates gaps linearly.

## ESP32 → laptop JSON (WebSocket text frames)

```json
{"type":"status","device":"esp32","rssi":-58,"mic_level":0.004,"mpu_ok":true,"acc":[0.02,-0.1,0.99],
 "measuring":false,"peer":{"online":true,"ip":"192.168.1.61","rssi":-52,"collecting":false,"ppg":14739,"gsr":13139,"ads":true}}
{"type":"peer_event","event":"started|ack|no_ack|peer_done|motion_done","id":"m123", ...}
```

Laptop → ESP32: `measure_start`, `measure_stop`, `mute`, `unmute` (the mic is muted while the laptop speaks).
