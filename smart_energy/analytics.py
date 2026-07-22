from __future__ import annotations

import csv
from dataclasses import dataclass, field
import datetime
import math
from pathlib import Path
import time
from typing import Sequence, Any

from .config import GridConfig
from .hardware_bridge import RawSensorSample


@dataclass(frozen=True)
class EnergyTelemetry:
    timestamp: float
    voltage: float           # Volts AC RMS
    current: float           # Amperes RMS
    active_power: float      # Watts (P)
    apparent_power: float    # VA (S)
    reactive_power: float    # VAR (Q)
    power_factor: float      # PF 0.0 - 1.0
    frequency: float         # Hz
    cumulative_kwh: float    # kWh accumulated
    estimated_cost: float    # Accumulated cost ($)
    tariff_tier: str         # "PEAK", "OFF_PEAK", "NIGHT"
    anomalies: tuple[str, ...]
    is_simulated: bool


class EnergyAnalyticsEngine:
    """Advanced electrical signal processing, multi-tariff energy accounting, and anomaly detection."""

    def __init__(self, config: GridConfig):
        self.config = config
        self.cumulative_energy_joules: float = 0.0
        self._last_sample_time: float | None = None
        self.total_anomalies_detected: int = 0
        self.recent_anomalies: list[dict[str, Any]] = []

    def _determine_tariff(self, dt_obj: datetime.datetime) -> tuple[str, float]:
        """Determines time-of-use (TOU) tariff tier and rate ($/kWh)."""
        hour = dt_obj.hour
        # Peak hours: 17:00 - 22:00 (Multiplier 1.5x)
        if 17 <= hour < 22:
            return "PEAK", self.config.cost_per_kwh * 1.5
        # Night hours: 22:00 - 06:00 (Multiplier 0.7x)
        if hour >= 22 or hour < 6:
            return "NIGHT", self.config.cost_per_kwh * 0.7
        # Standard Off-Peak hours: 06:00 - 17:00 (Multiplier 1.0x)
        return "OFF_PEAK", self.config.cost_per_kwh

    def process_sample(self, raw: RawSensorSample) -> EnergyTelemetry:
        now = raw.timestamp
        dt = 0.0
        if self._last_sample_time is not None:
            dt = max(0.0, now - self._last_sample_time)
        self._last_sample_time = now

        p_active = raw.power if raw.power > 0 else (raw.voltage * raw.current * raw.power_factor)
        s_apparent = raw.voltage * raw.current
        q_reactive = math.sqrt(max(0.0, (s_apparent ** 2) - (p_active ** 2)))

        dt_obj = datetime.datetime.fromtimestamp(now)
        tariff_tier, effective_rate = self._determine_tariff(dt_obj)

        if dt > 0 and dt < 30.0:
            self.cumulative_energy_joules += p_active * dt

        cumulative_kwh = self.cumulative_energy_joules / 3_600_000.0
        estimated_cost = cumulative_kwh * effective_rate

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
            tariff_tier=tariff_tier,
            anomalies=tuple(anomalies),
            is_simulated=raw.is_simulated,
        )


def export_telemetry_to_csv(rows: Sequence[dict[str, Any]], output_file: str | Path) -> Path:
    out_path = Path(output_file)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "timestamp", "datetime_str", "voltage", "current",
        "active_power", "apparent_power", "reactive_power",
        "power_factor", "frequency", "cumulative_kwh", "estimated_cost",
        "tariff_tier", "anomalies_json", "is_simulated"
    ]

    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            row_data = {k: r.get(k, "") for k in fieldnames}
            writer.writerow(row_data)

    return out_path
