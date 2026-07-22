from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import random
import threading
import time
from typing import Callable, Optional

from .config import HardwareConfig

logger = logging.getLogger("smart_energy.hardware_bridge")


@dataclass(frozen=True)
class RawSensorSample:
    timestamp: float
    voltage: float
    current: float
    power: float
    power_factor: float
    frequency: float
    relay_state: bool
    is_simulated: bool


class IoTDataReceiver:
    def __init__(self, config: HardwareConfig):
        self.config = config
        self._stopped = threading.Event()
        self._thread: threading.Thread | None = None
        self._serial = None
        self.is_connected: bool = False
        self.latest_sample: RawSensorSample | None = None
        self._subscribers: list[Callable[[RawSensorSample], None]] = []

        self._sim_appliance_state = 0
        self._sim_state_timer = time.time()

    def subscribe(self, callback: Callable[[RawSensorSample], None]) -> None:
        self._subscribers.append(callback)

    def start(self) -> IoTDataReceiver:
        self._stopped.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        return self

    def _open_serial(self) -> bool:
        if not self.config.port:
            return False
        try:
            import serial
            self._serial = serial.Serial(self.config.port, self.config.baudrate, timeout=self.config.timeout)
            logger.info(f"Connected to physical IoT Energy Hardware on {self.config.port} @ {self.config.baudrate} baud.")
            self.is_connected = True
            return True
        except Exception as exc:
            logger.warning(f"Could not open physical serial port '{self.config.port}': {exc}. Switching to emulator.")
            self.is_connected = False
            return False

    def _generate_synthetic_sample(self) -> RawSensorSample:
        now = time.time()
        if now - self._sim_state_timer > 6.0:
            self._sim_appliance_state = (self._sim_appliance_state + 1) % 3
            self._sim_state_timer = now

        base_v = 230.0 + random.uniform(-1.5, 1.5)
        freq = 50.0 + random.uniform(-0.1, 0.1)

        if self._sim_appliance_state == 0:
            curr = 1.2 + random.uniform(-0.1, 0.2)
            pf = 0.91 + random.uniform(-0.02, 0.02)
        elif self._sim_appliance_state == 1:
            curr = 9.8 + random.uniform(-0.3, 0.3)
            pf = 0.99
        else:
            curr = 6.4 + random.uniform(-0.4, 0.4)
            pf = 0.76 + random.uniform(-0.03, 0.03)

        power = base_v * curr * pf

        return RawSensorSample(
            timestamp=now,
            voltage=round(base_v, 2),
            current=round(curr, 2),
            power=round(power, 2),
            power_factor=round(pf, 2),
            frequency=round(freq, 1),
            relay_state=True,
            is_simulated=True,
        )

    def _run_loop(self) -> None:
        has_physical = self._open_serial()

        while not self._stopped.is_set():
            sample: RawSensorSample | None = None

            if has_physical and self._serial is not None and self._serial.is_open:
                try:
                    line = self._serial.readline().decode("utf-8", errors="ignore").strip()
                    if line.startswith("{") and line.endswith("}"):
                        data = json.loads(line)
                        sample = RawSensorSample(
                            timestamp=time.time(),
                            voltage=float(data.get("voltage", 230.0)),
                            current=float(data.get("current", 0.0)),
                            power=float(data.get("power", 0.0)),
                            power_factor=float(data.get("power_factor", 1.0)),
                            frequency=float(data.get("frequency", 50.0)),
                            relay_state=bool(data.get("relay_state", True)),
                            is_simulated=False,
                        )
                except Exception as exc:
                    logger.error(f"Error parsing serial JSON: {exc}")

            if sample is None:
                if self.config.use_simulation_fallback:
                    sample = self._generate_synthetic_sample()
                    time.sleep(self.config.sampling_interval_seconds)
                else:
                    time.sleep(0.1)
                    continue

            self.latest_sample = sample
            for cb in self._subscribers:
                try:
                    cb(sample)
                except Exception as e:
                    logger.error(f"Error in subscriber callback: {e}")

    def send_relay_command(self, command: str) -> bool:
        if self._serial is not None and self._serial.is_open:
            try:
                self._serial.write(f"{command}\n".encode("utf-8"))
                self._serial.flush()
                return True
            except Exception as exc:
                return False
        return True

    def stop(self) -> None:
        self._stopped.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        if self._serial is not None:
            try:
                self._serial.close()
            except Exception:
                pass
            self._serial = None
