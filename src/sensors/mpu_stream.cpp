#include "mpu_stream.h"
#include "../config.h"

#include <Arduino.h>
#include <Wire.h>
#include <MPU6050_light.h>

namespace motion {
namespace {
MPU6050 g_mpu(Wire);
bool    g_ok = false;
}

bool begin() {
    Wire.begin(MPU_SDA_PIN, MPU_SCL_PIN);
    Wire.setClock(400000);
    byte st = g_mpu.begin();            // default range: +/-2 g, +/-250 deg/s
    if (st != 0) {
        Serial.printf("[mpu] MPU6050 init failed (status %d) - check SDA=%d SCL=%d, AD0->GND\n",
                      st, MPU_SDA_PIN, MPU_SCL_PIN);
        g_ok = false;
        return false;
    }
    // Gyro offsets only. Accelerometer offsets are NOT calibrated on purpose:
    // that would assume the board lies flat and would remove gravity, but on
    // a wrist the orientation is arbitrary and WESAD's E4 ACC includes gravity.
    Serial.println("[mpu] calibrating gyro, keep the sensor still (1 s)...");
    g_mpu.calcOffsets(true, false);
    g_ok = true;
    Serial.println("[mpu] ready");
    return true;
}

bool ok() { return g_ok; }

bool read(float acc[3], float gyro[3]) {
    if (!g_ok) return false;
    g_mpu.update();
    acc[0] = g_mpu.getAccX();  acc[1] = g_mpu.getAccY();  acc[2] = g_mpu.getAccZ();
    gyro[0] = g_mpu.getGyroX(); gyro[1] = g_mpu.getGyroY(); gyro[2] = g_mpu.getGyroZ();
    return true;
}

}  // namespace motion
