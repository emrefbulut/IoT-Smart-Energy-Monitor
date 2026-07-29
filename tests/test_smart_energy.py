import datetime
import sqlite3
import time
from pathlib import Path
import pytest

from smart_energy.config import load_energy_settings, EnergyAppSettings, GridConfig, HardwareConfig
from smart_energy.hardware_bridge import RawSensorSample, IoTDataReceiver
from smart_energy.analytics import EnergyAnalyticsEngine
from smart_energy.database import AsyncEnergyDB


def _sample_at(when: datetime.datetime, power_w: float) -> RawSensorSample:
    """Yerel saat dilimine gore sabit bir zaman damgasiyla olcum uretir.

    Tarife katmani `datetime.fromtimestamp` ile yerel saati okudugu icin
    zaman damgasini yerel bir datetime'dan uretmek testi zaman diliminden
    bagimsiz kilar.
    """
    return RawSensorSample(
        timestamp=when.timestamp(),
        voltage=230.0,
        current=power_w / 230.0,
        power=power_w,
        power_factor=1.0,
        frequency=50.0,
        relay_state=True,
        is_simulated=True,
    )

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


def test_tou_cost_prices_each_interval_at_its_own_tariff():
    """Gecmis tuketim, saat degisince yeniden fiyatlanmamalidir.

    Regresyon: maliyet `cumulative_kwh * anlik_tarife` olarak hesaplaniyordu.
    OFF_PEAK'te biriken enerji, saat 17:00'de PEAK'e gecince 1.5x ile yeniden
    fiyatlaniyor ve maliyet gercekte olandan yuksek cikiyordu.
    """
    # Telemetri maliyeti 4 basamaga yuvarladigi icin, tarife degerini yuvarlama
    # adiminin (1e-4) belirgin sekilde ustunde kalacak buyuklukte seciyoruz.
    base_rate = 5.0
    engine = EnergyAnalyticsEngine(GridConfig(cost_per_kwh=base_rate, spike_power_threshold_kw=99.0))

    # 3600 W sabit yuk: 10 saniyede tam olarak 0.01 kWh.
    day = datetime.datetime(2026, 3, 10, 16, 59, 40)
    engine.process_sample(_sample_at(day, 3600.0))  # ilk ornek yalnizca zamani kurar

    off_peak = engine.process_sample(_sample_at(day + datetime.timedelta(seconds=10), 3600.0))
    assert off_peak.tariff_tier == "OFF_PEAK"
    assert off_peak.cumulative_kwh == pytest.approx(0.01, abs=1e-6)
    assert off_peak.estimated_cost == pytest.approx(0.01 * base_rate, abs=1e-6)

    # 17:00 -> PEAK. Yeni 0.01 kWh 1.5x ile fiyatlanir, onceki 0.01 kWh degismez.
    peak = engine.process_sample(_sample_at(day + datetime.timedelta(seconds=20), 3600.0))
    assert peak.tariff_tier == "PEAK"
    assert peak.cumulative_kwh == pytest.approx(0.02, abs=1e-6)

    expected = (0.01 * base_rate) + (0.01 * base_rate * 1.5)
    assert peak.estimated_cost == pytest.approx(expected, abs=1e-6)

    # Hatali davranis tam olarak bu deger olurdu; ona esit olmamali.
    naive = peak.cumulative_kwh * base_rate * 1.5
    assert peak.estimated_cost != pytest.approx(naive, abs=1e-6)


def test_tou_cost_never_decreases_across_tariff_boundaries():
    """Tarife ucuzlasa bile birikmis maliyet asla dusmez."""
    engine = EnergyAnalyticsEngine(GridConfig(cost_per_kwh=5.0, spike_power_threshold_kw=99.0))

    # 21:59:40 -> 22:00:10 araligi PEAK'ten (1.5x) NIGHT'a (0.7x) geciyor.
    start = datetime.datetime(2026, 3, 10, 21, 59, 40)
    costs = []
    tiers = []
    for step in range(0, 40, 10):
        telemetry = engine.process_sample(_sample_at(start + datetime.timedelta(seconds=step), 3600.0))
        costs.append(telemetry.estimated_cost)
        tiers.append(telemetry.tariff_tier)

    assert tiers == ["PEAK", "PEAK", "NIGHT", "NIGHT"]
    assert costs == sorted(costs), f"maliyet geriye dogru dustu: {costs}"
    # Ucuz tarifeye gecmek maliyeti dondurmamali; artis surmelidir.
    assert costs[-1] > costs[1]


def test_relay_command_reports_failure_without_hardware():
    """Donanim yokken komut basarili gibi raporlanmamali."""
    receiver = IoTDataReceiver(HardwareConfig(port=None))
    assert receiver.send_relay_command("RELAY_ON") is False
