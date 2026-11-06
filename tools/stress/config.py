"""All laptop-side settings for the stress system. Ports must match the firmware."""
import os
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("STRESS_DATA", TOOLS / "data"))                       # sessions, baseline, gsr calibration
MODEL_PATH = Path(os.environ.get("STRESS_MODEL", TOOLS / "ml" / "models" / "stress_model.joblib"))
DASHBOARD_DIR = TOOLS / "dashboard"

# ---- network -------------------------------------------------------------
WS_HOST, WS_PORT = "0.0.0.0", 8765              # ESP32 audio/control WebSocket
HTTP_HOST, HTTP_PORT = "0.0.0.0", 8080          # dashboard  -> http://<laptop>:8080
PORT_ESP8266_CONTROL = 4210                     # ESP8266 listens for START/STOP
PORT_VITALS = 4211                              # ESP8266 -> laptop PPG/GSR
PORT_STATUS = 4212                              # ESP8266 heartbeats (broadcast) / ACKs
PORT_MOTION = 4213                              # ESP32 -> laptop MPU6050

# ---- measurement -----------------------------------------------------------
MEASURE_S = 60          # = WESAD/paper feature window (Schmidt et al. 2018, Sec. 4.1)
CALIBRATE_S = 180       # personal relaxed baseline = build_dataset.CALIB_S
PREVIEW_S = 30          # live signal check, no prediction
ACK_TIMEOUT_S = 2.0     # wait this long for the ESP32 relay before contacting the ESP8266 directly
FS_PPG = 64             # ESP8266 sample rate (both channels)
FS_ACC = 32             # ESP32 MPU6050 rate

# ---- ADS1115 / Grove GSR conversion -------------------------------------------
ADS_FSR_V = 4.096       # PGA full-scale used by the firmware (+/-4.096 V)
SENSOR_VCC = 3.3        # Grove GSR supply voltage
# Grove formula (wiki.seeedstudio.com/Grove-GSR_Sensor):
#   R_human = ((1024 + 2*X) * 10000) / (X_cal - X)    X = 10-bit equivalent reading
# X_cal = reading with the sensor NOT worn. Set it from the dashboard
# ("GSR calibrate" button) or here; stored in data/gsr_calibration.json.
GSR_DEFAULT_CAL = 512.0

# ---- stress level from P(stress) ------------------------------------------------
LEVELS = [(0.35, "low"), (0.65, "moderate"), (1.01, "high")]
