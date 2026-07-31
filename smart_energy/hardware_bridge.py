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


def parse_sensor_payload(data: dict, is_simulated: bool = False) -> RawSensorSample:
    """Cihazdan gelen JSON govdesini olcume cevirir.

    Seri port ve MQTT (WiFi) yollarinin ikisi de bunu kullanir, boylece iki
    tasima katmani birebir ayni alanlari ve varsayilanlari uygular.
    """
    return RawSensorSample(
        timestamp=time.time(),
        voltage=float(data.get("voltage", 230.0)),
        current=float(data.get("current", 0.0)),
        power=float(data.get("power", 0.0)),
        power_factor=float(data.get("power_factor", 1.0)),
        frequency=float(data.get("frequency", 50.0)),
        relay_state=bool(data.get("relay_state", True)),
        is_simulated=is_simulated,
    )


class IoTDataReceiver:
    RECONNECT_MAX_DELAY_SECONDS = 30.0

    def __init__(self, config: HardwareConfig):
        self.config = config
        self._stopped = threading.Event()
        self._thread: threading.Thread | None = None
        self._serial = None
        self.is_connected: bool = False
        self.latest_sample: RawSensorSample | None = None
        self._subscribers: list[Callable[[RawSensorSample], None]] = []

        self._reconnect_delay: float = 0.0
        self._next_reconnect_at: float = 0.0

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
            self._reconnect_delay = 0.0
            return True
        except Exception as exc:
            logger.warning(f"Could not open physical serial port '{self.config.port}': {exc}. Switching to emulator.")
            self._serial = None
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

    def _close_serial(self, reason: str) -> None:
        """Donanim koptugunda portu kapatir ve yeniden baglanmaya hazir hale getirir."""
        if self._serial is not None:
            try:
                self._serial.close()
            except Exception:
                pass
        self._serial = None
        if self.is_connected:
            logger.warning(f"Physical hardware link lost ({reason}). Falling back until it returns.")
        self.is_connected = False

    def _should_retry_connection(self) -> bool:
        """Yeniden baglanma denemeleri arasinda ustel bekleme uygular."""
        if not self.config.port:
            return False
        if time.monotonic() < self._next_reconnect_at:
            return False

        self._reconnect_delay = min(
            self._reconnect_delay * 2 if self._reconnect_delay else 1.0,
            self.RECONNECT_MAX_DELAY_SECONDS,
        )
        self._next_reconnect_at = time.monotonic() + self._reconnect_delay
        return True

    def _run_loop(self) -> None:
        self._open_serial()

        while not self._stopped.is_set():
            sample: RawSensorSample | None = None

            # Donanim baglantisi yoksa periyodik olarak yeniden baglanmayi dene.
            # Onceden bu bayrak dongu basinda bir kez hesaplaniyordu; kablo
            # cekildiginde surec sonsuza kadar sentetik veri uretmeye devam
            # ediyor ve bir daha asla gercek olcume donmuyordu.
            if self._serial is None and self._should_retry_connection():
                self._open_serial()

            if self._serial is not None and self._serial.is_open:
                try:
                    line = self._serial.readline().decode("utf-8", errors="ignore").strip()
                    if line.startswith("{") and line.endswith("}"):
                        sample = parse_sensor_payload(json.loads(line), is_simulated=False)
                        self._reconnect_delay = 0.0
                except json.JSONDecodeError as exc:
                    logger.error(f"Error parsing serial JSON: {exc}")
                except Exception as exc:
                    # Okuma hatasi genellikle portun dusmesi anlamina gelir.
                    self._close_serial(str(exc))

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
        """Roleye komut gonderir. Donanim yoksa False doner - basarisiz bir
        komutu basarili gibi raporlamak, cagiranin roleyi kontrol ettigini
        sanmasina yol acar."""
        if self._serial is None or not self._serial.is_open:
            logger.warning(f"Relay command '{command}' dropped: no physical hardware link.")
            return False

        try:
            self._serial.write(f"{command}\n".encode("utf-8"))
            self._serial.flush()
            return True
        except Exception as exc:
            logger.error(f"Error sending relay command '{command}': {exc}")
            self._close_serial(str(exc))
            return False

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
