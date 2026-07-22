from __future__ import annotations

from dataclasses import dataclass, field
import math
import time
from typing import Sequence

from .config import GridConfig
from .hardware_bridge import RawSensorSample


@dataclass(frozen=True)
class EnergyTelemetry:
    timestamp: float
    voltage: float
    current: float
    active_power: float
    apparent_power: float
    reactive_power: float
    power_factor: float
    frequency: float
    cumulative_kwh: float
    estimated_cost: float
    anomalies: tuple[str, ...]
    is_simulated: bool


class EnergyAnalyticsEngine:
    def __init__(self, config: GridConfig):
        self.config = config
        self.cumulative_energy_joules: float = 0.0
        self._last_sample_time: float | None = None
        self.total_anomalies_detected: int = 0
        self.recent_anomalies: list[dict] = []

    def process_sample(self, raw: RawSensorSample) -> EnergyTelemetry:
        now = raw.timestamp
        dt = 0.0
        if self._last_sample_time is not None:
            dt = max(0.0, now - self._last_sample_time)
        self._last_sample_time = now

        p_active = raw.power if raw.power > 0 else (raw.voltage * raw.current * raw.power_factor)
        s_apparent = raw.voltage * raw.current
        q_reactive = math.sqrt(max(0.0, (s_apparent ** 2) - (p_active ** 2)))

        if dt > 0 and dt < 30.0:
            self.cumulative_energy_joules += p_active * dt

        cumulative_kwh = self.cumulative_energy_joules / 3_600_000.0
        estimated_cost = cumulative_kwh * self.config.cost_per_kwh

        anomalies: list[str] = []
        if raw.voltage < self.config.voltage_sag_threshold:
            anomalies.append(f"VOLTAGE_SAG ({raw.voltage:.1f}V < {self.config.voltage_sag_threshold}V)")
        elif raw.voltage > self.config.voltage_swell_threshold:
            anomalies.append(f"VOLTAGE_SWELL ({raw.voltage:.1f}V > {self.config.voltage_swell_threshold}V)")

        if raw.power_factor < self.config.low_pf_threshold and raw.current > 0.5:
            anomalies.append(f"LOW_POWER_FACTOR ({raw.power_factor:.2f} < {self.config.low_pf_threshold})")

        p_kw = p_active / 1000.0
        if p_kw >= self.config.spike_power_threshold_kw:
            anomalies.append(f"CONSUMPTION_SPIKE ({p_kw:.2f}kW >= {self.config.spike_power_threshold_kw}kW)")

        if anomalies:
            self.total_anomalies_detected += len(anomalies)
            self.recent_anomalies.append({
                "timestamp": now,
                "anomalies": list(anomalies),
                "voltage": raw.voltage,
                "current": raw.current,
                "power_kw": round(p_kw, 3),
            })
            if len(self.recent_anomalies) > 50:
                self.recent_anomalies.pop(0)

        return EnergyTelemetry(
            timestamp=now,
            voltage=round(raw.voltage, 2),
            current=round(raw.current, 2),
            active_power=round(p_active, 2),
            apparent_power=round(s_apparent, 2),
            reactive_power=round(q_reactive, 2),
            power_factor=round(raw.power_factor, 2),
            frequency=round(raw.frequency, 1),
            cumulative_kwh=round(cumulative_kwh, 4),
            estimated_cost=round(estimated_cost, 4),
            anomalies=tuple(anomalies),
            is_simulated=raw.is_simulated,
        )
