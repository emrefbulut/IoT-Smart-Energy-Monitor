import sqlite3
import time
from pathlib import Path
import pytest

from smart_energy.config import load_energy_settings, EnergyAppSettings, GridConfig
from smart_energy.hardware_bridge import RawSensorSample, IoTDataReceiver
from smart_energy.analytics import EnergyAnalyticsEngine
from smart_energy.database import AsyncEnergyDB

def test_load_energy_settings(tmp_path: Path):
    cfg_file = tmp_path / "energy_test.yaml"
    cfg_file.write_text("""
hardware:
  port: "COM3"
  baudrate: 115200
grid:
  nominal_voltage: 230.0
  cost_per_kwh: 0.20
""", encoding="utf-8")

    settings = load_energy_settings(cfg_file)
    assert isinstance(settings, EnergyAppSettings)
    assert settings.hardware.port == "COM3"
    assert settings.grid.cost_per_kwh == 0.20

def test_electrical_analytics_and_anomalies():
    engine = EnergyAnalyticsEngine(GridConfig(
        voltage_sag_threshold=207.0,
        voltage_swell_threshold=253.0,
        low_pf_threshold=0.85,
        spike_power_threshold_kw=2.0,
        cost_per_kwh=0.15,
    ))

    s1 = RawSensorSample(
        timestamp=time.time(),
        voltage=230.0,
        current=2.0,
        power=460.0,
        power_factor=1.0,
        frequency=50.0,
        relay_state=True,
        is_simulated=True,
    )
    t1 = engine.process_sample(s1)
    assert t1.active_power == 460.0
    assert t1.tariff_tier in ("PEAK", "OFF_PEAK", "NIGHT")
    assert len(t1.anomalies) == 0

    s_sag = RawSensorSample(
        timestamp=time.time() + 1,
        voltage=195.0,
        current=2.0,
        power=390.0,
        power_factor=1.0,
        frequency=50.0,
        relay_state=True,
        is_simulated=True,
    )
    t_sag = engine.process_sample(s_sag)
    assert any("VOLTAGE_SAG" in a for a in t_sag.anomalies)

    s_low_pf = RawSensorSample(
        timestamp=time.time() + 2,
        voltage=230.0,
        current=4.0,
        power=644.0,
        power_factor=0.70,
        frequency=50.0,
        relay_state=True,
        is_simulated=True,
    )
    t_pf = engine.process_sample(s_low_pf)
    assert any("LOW_POWER_FACTOR" in a for a in t_pf.anomalies)

def test_async_energy_database_and_csv_export(tmp_path: Path):
    db_path = tmp_path / "energy_test.sqlite3"
    csv_path = tmp_path / "energy_report.csv"
    from smart_energy.config import StorageConfig
    db = AsyncEnergyDB(StorageConfig(sqlite_path=str(db_path)))

    engine = EnergyAnalyticsEngine(GridConfig())
    s1 = RawSensorSample(
        timestamp=time.time(),
        voltage=231.0,
        current=3.0,
        power=693.0,
        power_factor=1.0,
        frequency=50.0,
        relay_state=True,
        is_simulated=True,
    )
    t1 = engine.process_sample(s1)
    db.record(t1)
    db.close()

    rows = db.fetch_recent(limit=10)
    assert len(rows) == 1
    assert rows[0]["voltage"] == 231.0
    assert rows[0]["active_power"] == 693.0

    target = db.export_csv(csv_path)
    assert target.exists()
    content = target.read_text(encoding="utf-8")
    assert "active_power" in content
    assert "231.0" in content
