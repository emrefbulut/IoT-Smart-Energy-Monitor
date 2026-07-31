from __future__ import annotations

import json
import logging
from typing import Any, Callable

from .analytics import EnergyTelemetry
from .config import MqttConfig
from .hardware_bridge import RawSensorSample, parse_sensor_payload
from .load_shedding import LoadSheddingDecision

logger = logging.getLogger("smart_energy.mqtt")


def telemetry_topic(config: MqttConfig) -> str:
    return f"{config.base_topic}/telemetry"


def alert_topic(config: MqttConfig) -> str:
    return f"{config.base_topic}/alerts"


def load_event_topic(config: MqttConfig) -> str:
    return f"{config.base_topic}/load-shedding"


def device_topic(config: MqttConfig) -> str:
    """ESP32'nin ham olcumlerini yayinladigi konu (WiFi yolu)."""
    return f"{config.base_topic}/device/telemetry"


def build_telemetry_payload(telemetry: EnergyTelemetry) -> dict[str, Any]:
    """Yayinlanacak govdeyi uretir.

    Ag katmanindan ayri tutuluyor ki broker olmadan test edilebilsin.
    """
    return {
        "timestamp": telemetry.timestamp,
        "voltage": telemetry.voltage,
        "current": telemetry.current,
        "active_power": telemetry.active_power,
        "apparent_power": telemetry.apparent_power,
        "reactive_power": telemetry.reactive_power,
        "power_factor": telemetry.power_factor,
        "frequency": telemetry.frequency,
        "cumulative_kwh": telemetry.cumulative_kwh,
        "estimated_cost": telemetry.estimated_cost,
        "tariff_tier": telemetry.tariff_tier,
        "anomaly_count": len(telemetry.anomalies),
        # Sentetik veri gercek olcumden ayirt edilebilir kalmalidir.
        "is_simulated": telemetry.is_simulated,
    }


def build_alert_payload(telemetry: EnergyTelemetry) -> dict[str, Any]:
    return {
        "timestamp": telemetry.timestamp,
        "anomalies": list(telemetry.anomalies),
        "voltage": telemetry.voltage,
        "active_power": telemetry.active_power,
        "power_factor": telemetry.power_factor,
        "is_simulated": telemetry.is_simulated,
    }


def build_load_event_payload(decision: LoadSheddingDecision) -> dict[str, Any]:
    return {
        "action": decision.action,
        "reason": decision.reason,
        "shed_active": decision.shed_active,
        "power_kw": round(decision.power_kw, 3),
        "command": decision.command,
    }


class MqttBridge:
    """Telemetriyi MQTT'ye yayinlar ve istege bagli olarak cihazdan dinler.

    `paho-mqtt` kurulu degilse veya yapilandirma kapaliysa tum cagrilar sessizce
    ise yaramaz hale gelir; boylece MQTT olmayan bir kurulumda uygulama aynen
    calismaya devam eder.
    """

    def __init__(self, config: MqttConfig):
        self.config = config
        self._client: Any = None
        self._connected = False
        self._warned = False

    @property
    def active(self) -> bool:
        return self._client is not None and self._connected

    def start(self) -> bool:
        if not self.config.enabled:
            return False

        try:
            import paho.mqtt.client as mqtt
        except ImportError:
            logger.warning(
                "MQTT yapilandirmasi acik ama paho-mqtt kurulu degil. "
                'Kurmak icin: pip install -e ".[mqtt]" - MQTT olmadan devam ediliyor.'
            )
            return False

        try:
            # paho-mqtt 2.x, Client() cagrisinda callback API surumunu zorunlu
            # kiliyor; 1.x'te boyle bir parametre yok. Iki surumle de calisalim.
            if hasattr(mqtt, "CallbackAPIVersion"):
                client = mqtt.Client(
                    mqtt.CallbackAPIVersion.VERSION1,
                    client_id=self.config.client_id or None,
                )
            else:
                client = mqtt.Client(client_id=self.config.client_id or None)

            if self.config.username:
                client.username_pw_set(self.config.username, self.config.password or None)
            if self.config.tls:
                client.tls_set()

            client.connect(self.config.host, self.config.port, keepalive=30)
            client.loop_start()

            self._client = client
            self._connected = True
            logger.info(
                f"MQTT connected to {self.config.host}:{self.config.port} "
                f"(base topic '{self.config.base_topic}')"
            )
            return True
        except Exception as exc:
            logger.warning(f"MQTT baglantisi kurulamadi ({exc}). MQTT olmadan devam ediliyor.")
            self._client = None
            self._connected = False
            return False

    def _publish(self, topic: str, payload: dict[str, Any]) -> bool:
        if not self.active:
            return False

        try:
            self._client.publish(topic, json.dumps(payload), qos=self.config.qos)
            return True
        except Exception as exc:
            if not self._warned:
                logger.error(f"MQTT yayini basarisiz: {exc}")
                self._warned = True
            return False

    def publish_telemetry(self, telemetry: EnergyTelemetry) -> bool:
        return self._publish(telemetry_topic(self.config), build_telemetry_payload(telemetry))

    def publish_alert(self, telemetry: EnergyTelemetry) -> bool:
        if not telemetry.anomalies:
            return False

        return self._publish(alert_topic(self.config), build_alert_payload(telemetry))

    def publish_load_event(self, decision: LoadSheddingDecision) -> bool:
        if decision.command is None:
            return False

        return self._publish(load_event_topic(self.config), build_load_event_payload(decision))

    def subscribe_device_samples(self, on_sample: Callable[[RawSensorSample], None]) -> bool:
        """ESP32'nin WiFi uzerinden yayinladigi ham olcumleri dinler.

        Seri port yerine WiFi ile veri almanin yolu budur; iki kaynak da ayni
        `RawSensorSample` tipini uretir.
        """
        if not self.active:
            return False

        topic = device_topic(self.config)

        def handle(_client: Any, _userdata: Any, message: Any) -> None:
            try:
                data = json.loads(message.payload.decode("utf-8"))
            except Exception as exc:
                logger.error(f"MQTT cihaz mesaji cozulemedi: {exc}")
                return

            try:
                on_sample(parse_sensor_payload(data, is_simulated=False))
            except Exception as exc:
                logger.error(f"MQTT cihaz olcumu islenemedi: {exc}")

        try:
            self._client.message_callback_add(topic, handle)
            self._client.subscribe(topic, qos=self.config.qos)
            logger.info(f"MQTT subscribed to device telemetry on '{topic}'")
            return True
        except Exception as exc:
            logger.warning(f"MQTT cihaz konusuna abone olunamadi: {exc}")
            return False

    def stop(self) -> None:
        if self._client is None:
            return

        try:
            self._client.loop_stop()
            self._client.disconnect()
        except Exception:
            pass
        finally:
            self._client = None
            self._connected = False
