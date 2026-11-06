#pragma once
#include <stdint.h>

// MPU6050 (accelerometer + gyro) on I2C. Used only by the coordinator task.
namespace motion {

bool begin();                       // I2C + sensor init + gyro offset calibration
bool ok();
// acc in g, gyro in deg/s. Returns false if the sensor is not available.
bool read(float acc[3], float gyro[3]);

}  // namespace motion
