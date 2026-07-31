import json
import time

from smart_energy.analytics import EnergyAnalyticsEngine
from smart_energy.config import GridConfig, MqttConfig
from smart_energy.hardware_bridge import RawSensorSample, parse_sensor_payload
from smart_energy.load_shedding import LoadSheddingDecision
from smart_energy.mqtt import (
    MqttBridge,
    alert_topic,
    build_alert_payload,
    build_load_event_payload,
    build_telemetry_payload,
    device_topic,
    load_event_topic,
    telemetry_topic,
)


def sample_telemetry(power_w: float = 690.0, voltage: float = 230.0):
    engine = EnergyAnalyticsEngine(GridConfig(spike_power_threshold_kw=99.0))
    return engine.process_sample(
        RawSensorSample(
            timestamp=time.time(),
            voltage=voltage,
            current=power_w / voltage,
            power=power_w,
            power_factor=1.0,
            frequency=50.0,
            relay_state=True,
            is_simulated=True,
        )
    )


def test_topics_derive_from_base_topic():
    config = MqttConfig(base_topic="site-a/energy")

    assert telemetry_topic(config) == "site-a/energy/telemetry"
    assert alert_topic(config) == "site-a/energy/alerts"
    assert load_event_topic(config) == "site-a/energy/load-shedding"
    assert device_topic(config) == "site-a/energy/device/telemetry"


def test_telemetry_payload_is_json_serialisable_and_flags_simulation():
    payload = build_telemetry_payload(sample_telemetry())
    encoded = json.loads(json.dumps(payload))

    assert encoded["active_power"] == 690.0
    assert encoded["tariff_tier"] in ("PEAK", "OFF_PEAK", "NIGHT")
    # Sentetik veri gercek olcum gibi gorunmemeli.
    assert encoded["is_simulated"] is True


def test_alert_payload_lists_anomalies():
    engine = EnergyAnalyticsEngine(GridConfig(voltage_sag_threshold=207.0))
    telemetry = engine.process_sample(
        RawSensorSample(
            timestamp=time.time(),
            voltage=190.0,
            current=2.0,
            power=380.0,
            power_factor=1.0,
            frequency=50.0,
            relay_state=True,
            is_simulated=True,
        )
    )

    payload = build_alert_payload(telemetry)
    assert any("VOLTAGE_SAG" in item for item in payload["anomalies"])


def test_load_event_payload_carries_action_and_command():
    decision = LoadSheddingDecision(
        action="SHED",
        reason="threshold_exceeded",
        shed_active=True,
        command="SHED_LOAD",
        power_kw=4.2,
    )

    payload = build_load_event_payload(decision)
    assert payload["action"] == "SHED"
    assert payload["command"] == "SHED_LOAD"
    assert payload["power_kw"] == 4.2


def test_bridge_is_inert_when_disabled():
    """MQTT kapaliyken hicbir cagri patlamamali ve hicbir sey yayinlanmamali."""
    bridge = MqttBridge(MqttConfig(enabled=False))

    assert bridge.start() is False
    assert bridge.active is False
    assert bridge.publish_telemetry(sample_telemetry()) is False
    assert bridge.publish_alert(sample_telemetry()) is False
    assert bridge.subscribe_device_samples(lambda _sample: None) is False
    bridge.stop()  # hata vermemeli


def test_bridge_does_not_publish_hold_decisions():
    """Aksiyon iceremeyen kararlar icin olay yayinlanmaz."""
    bridge = MqttBridge(MqttConfig(enabled=False))
    hold = LoadSheddingDecision(action="HOLD", reason="disabled", shed_active=False, command=None)

    assert bridge.publish_load_event(hold) is False


def test_device_payload_parses_into_the_same_sample_type():
    """Seri port ve WiFi yollari ayni alanlari uretmeli."""
    payload = {
        "voltage": 231.5,
        "current": 3.0,
        "power": 640.0,
        "power_factor": 0.92,
        "frequency": 49.9,
        "relay_state": False,
    }

    sample = parse_sensor_payload(payload, is_simulated=False)

    assert sample.voltage == 231.5
    assert sample.power == 640.0
    assert sample.relay_state is False
    assert sample.is_simulated is False


def test_device_payload_falls_back_to_defaults_for_missing_fields():
    sample = parse_sensor_payload({}, is_simulated=False)

    assert sample.voltage == 230.0
    assert sample.current == 0.0
    assert sample.frequency == 50.0
