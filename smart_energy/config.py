from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class HardwareConfig:
    port: str | None = None
    baudrate: int = 115200
    timeout: float = 1.0
    use_simulation_fallback: bool = True
    sampling_interval_seconds: float = 0.5


@dataclass(frozen=True)
class GridConfig:
    nominal_voltage: float = 230.0
    nominal_frequency: float = 50.0
    voltage_sag_threshold: float = 207.0
    voltage_swell_threshold: float = 253.0
    low_pf_threshold: float = 0.85
    spike_power_threshold_kw: float = 2.5
    cost_per_kwh: float = 0.15


@dataclass(frozen=True)
class StorageConfig:
    sqlite_path: str = "logs/energy_events.sqlite3"
    wal_mode: bool = True
    history_retention_days: int = 30


@dataclass(frozen=True)
class DashboardConfig:
    enabled: bool = True
    host: str = "0.0.0.0"
    port: int = 8050


@dataclass(frozen=True)
class EnergyAppSettings:
    hardware: HardwareConfig = field(default_factory=HardwareConfig)
    grid: GridConfig = field(default_factory=GridConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    dashboard: DashboardConfig = field(default_factory=DashboardConfig)


def load_energy_settings(path: str | Path = "config/energy_default.yaml") -> EnergyAppSettings:
    config_path = Path(path)
    raw = {}
    if config_path.exists():
        with config_path.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

    hw = raw.get("hardware", {})
    grid = raw.get("grid", {})
    storage = raw.get("storage", {})
    dash = raw.get("dashboard", {})

    return EnergyAppSettings(
        hardware=HardwareConfig(
            port=hw.get("port"),
            baudrate=int(hw.get("baudrate", 115200)),
            timeout=float(hw.get("timeout", 1.0)),
            use_simulation_fallback=bool(hw.get("use_simulation_fallback", True)),
            sampling_interval_seconds=float(hw.get("sampling_interval_seconds", 0.5)),
        ),
        grid=GridConfig(
            nominal_voltage=float(grid.get("nominal_voltage", 230.0)),
            nominal_frequency=float(grid.get("nominal_frequency", 50.0)),
            voltage_sag_threshold=float(grid.get("voltage_sag_threshold", 207.0)),
            voltage_swell_threshold=float(grid.get("voltage_swell_threshold", 253.0)),
            low_pf_threshold=float(grid.get("low_pf_threshold", 0.85)),
            spike_power_threshold_kw=float(grid.get("spike_power_threshold_kw", 2.5)),
            cost_per_kwh=float(grid.get("cost_per_kwh", 0.15)),
        ),
        storage=StorageConfig(
            sqlite_path=str(storage.get("sqlite_path", "logs/energy_events.sqlite3")),
            wal_mode=bool(storage.get("wal_mode", True)),
            history_retention_days=int(storage.get("history_retention_days", 30)),
        ),
        dashboard=DashboardConfig(
            enabled=bool(dash.get("enabled", True)),
            host=str(dash.get("host", "0.0.0.0")),
            port=int(dash.get("port", 8050)),
        ),
    )
