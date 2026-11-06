"""
Networking only: collects raw samples from both ESPs over UDP. No signal
processing here -- see vitals_features.py for that.

    ESP8266 (pulse + its own MPU6050) --UDP--> this laptop, port 4211
    ESP32   (MPU6050 only)            --UDP--> this laptop, port 4213

Both devices idle until sent "START,<duration_ms>" on their own control
port (ESP8266: 4210, ESP32: 4212), matching src/sensors/mpu_stream.cpp
and esp8266_vitals/src/main.cpp exactly -- change one side, change both.

Usage:
    receiver = VitalsReceiver(esp8266_ip="192.168.1.60", esp32_ip="192.168.1.61")
    await receiver.start_server()                      # once, at startup
    raw = await receiver.collect_raw(duration_s=15)     # on demand
    # raw = {"esp8266": [Esp8266Sample, ...], "esp32": [Esp32Sample, ...]}
"""
import asyncio
import socket
import time
from dataclasses import dataclass, field

ESP8266_CONTROL_PORT = 4210
ESP8266_DATA_PORT    = 4211
ESP32_CONTROL_PORT   = 4212
ESP32_DATA_PORT      = 4213


@dataclass
class Esp8266Sample:
    t: float       # seconds, relative to collection start
    pulse: float
    ax: float
    ay: float
    az: float
    gx: float
    gy: float
    gz: float


@dataclass
class Esp32Sample:
    t: float
    ax: float
    ay: float
    az: float
    gx: float
    gy: float
    gz: float


class _RawUdpListener(asyncio.DatagramProtocol):
    """Appends parsed lines to `buffer` while `armed` is true. `parse` turns
    the raw bytes into one dataclass instance, or returns None to drop it."""
    def __init__(self, armed_flag: list, buffer: list, t0_box: list, parse):
        self._armed = armed_flag     # single-element list used as a mutable box
        self._buffer = buffer
        self._t0 = t0_box
        self._parse = parse

    def datagram_received(self, data, addr):
        if not self._armed[0]:
            return
        sample = self._parse(data, time.monotonic() - self._t0[0])
        if sample is not None:
            self._buffer.append(sample)


def _parse_esp8266(data: bytes, t: float):
    try:
        _micros, pulse, ax, ay, az, gx, gy, gz = data.decode().strip().split(",")
        return Esp8266Sample(t=t, pulse=float(pulse), ax=float(ax), ay=float(ay),
                               az=float(az), gx=float(gx), gy=float(gy), gz=float(gz))
    except (ValueError, UnicodeDecodeError):
        return None


def _parse_esp32(data: bytes, t: float):
    try:
        _micros, ax, ay, az, gx, gy, gz = data.decode().strip().split(",")
        return Esp32Sample(t=t, ax=float(ax), ay=float(ay), az=float(az),
                             gx=float(gx), gy=float(gy), gz=float(gz))
    except (ValueError, UnicodeDecodeError):
        return None


class VitalsReceiver:
    def __init__(self, esp8266_ip: str, esp32_ip: str):
        self.esp8266_ip = esp8266_ip
        self.esp32_ip = esp32_ip
        self._armed = [False]
        self._t0 = [0.0]
        self._esp8266_buf: list[Esp8266Sample] = []
        self._esp32_buf: list[Esp32Sample] = []

    async def start_server(self):
        loop = asyncio.get_running_loop()
        await loop.create_datagram_endpoint(
            lambda: _RawUdpListener(self._armed, self._esp8266_buf, self._t0, _parse_esp8266),
            local_addr=("0.0.0.0", ESP8266_DATA_PORT),
        )
        await loop.create_datagram_endpoint(
            lambda: _RawUdpListener(self._armed, self._esp32_buf, self._t0, _parse_esp32),
            local_addr=("0.0.0.0", ESP32_DATA_PORT),
        )

    def _send_start(self, ip: str, port: int, duration_s: float) -> str | None:
        """Returns an error string on failure, None on success."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.sendto(f"START,{int(duration_s * 1000)}".encode(), (ip, port))
            return None
        except OSError as e:
            return repr(e)

    async def collect_raw(self, duration_s: float = 15.0) -> dict:
        # Clear in place -- the listener protocols hold a reference to
        # these exact list objects (passed in at start_server() time), so
        # rebinding self._esp8266_buf = [] here would silently orphan
        # their appends into the old list while this method returns the
        # new, empty one.
        self._esp8266_buf.clear()
        self._esp32_buf.clear()
        self._t0[0] = time.monotonic()
        self._armed[0] = True

        errors = {}
        if (e := self._send_start(self.esp8266_ip, ESP8266_CONTROL_PORT, duration_s)):
            errors["esp8266"] = e
        if (e := self._send_start(self.esp32_ip, ESP32_CONTROL_PORT, duration_s)):
            errors["esp32"] = e

        await asyncio.sleep(duration_s + 1.0)   # +1s margin for last packets to arrive
        self._armed[0] = False

        return {
            "esp8266": self._esp8266_buf,
            "esp32": self._esp32_buf,
            "errors": errors,   # non-empty means that device didn't get the START command
        }


if __name__ == "__main__":
    # Loopback smoke test -- no hardware needed. Sends fake packets to our
    # own listener ports and checks they land in the right buffers.
    async def main():
        receiver = VitalsReceiver(esp8266_ip="127.0.0.1", esp32_ip="127.0.0.1")
        await receiver.start_server()

        async def fake_devices():
            await asyncio.sleep(0.2)
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                for i in range(5):
                    s.sendto(f"{i*10000},512,0.01,0.02,0.98,1.0,2.0,3.0".encode(),
                              ("127.0.0.1", ESP8266_DATA_PORT))
                    s.sendto(f"{i*10000},0.03,0.04,0.97,1.1,2.1,3.1".encode(),
                              ("127.0.0.1", ESP32_DATA_PORT))
                    await asyncio.sleep(0.05)

        task = asyncio.create_task(fake_devices())
        raw = await receiver.collect_raw(duration_s=1.0)
        await task
        print(f"esp8266 samples: {len(raw['esp8266'])}  (expect 5)")
        print(f"esp32 samples:   {len(raw['esp32'])}  (expect 5)")
        print(f"errors: {raw['errors']}  (expect {{}} since nothing is actually listening "
              f"on the control ports here -- UDP send doesn't fail just because nobody's there)")
        assert len(raw["esp8266"]) == 5
        assert len(raw["esp32"]) == 5
        print("OK")

    asyncio.run(main())
