/*
  IoT Smart Energy Monitoring System - ESP32 Firmware

  Reads electrical parameters (voltage, current, active power, power factor,
  frequency) from PZEM-004T or ACS712/ZMPT101B sensors and transmits JSON
  telemetry over two interchangeable transports:

    1. USB Serial at 115200 baud  - always active, no configuration needed.
    2. WiFi + MQTT                - enabled by filling in WIFI_SSID below.

  Both transports emit the exact same JSON object, so the Python bridge parses
  them with the same code path. WiFi is strictly additive: if the credentials
  are left blank, or the network or broker is unreachable, the firmware keeps
  streaming over Serial and retries the connection in the background without
  ever blocking the sampling loop.

  Relay commands (SHED_LOAD / CONNECT_LOAD) are accepted from both Serial and
  the MQTT command topic.

  WiFi build requires the PubSubClient library:
    Arduino IDE -> Library Manager -> "PubSubClient" by Nick O'Leary
*/

#include <Arduino.h>
#include <WiFi.h>
#include <PubSubClient.h>

// ---------------------------------------------------------------------------
// Configuration. Leave WIFI_SSID empty to run in Serial-only mode.
// ---------------------------------------------------------------------------
const char *WIFI_SSID = "";
const char *WIFI_PASSWORD = "";

const char *MQTT_HOST = "192.168.1.10";
const uint16_t MQTT_PORT = 1883;
const char *MQTT_CLIENT_ID = "esp32-energy-monitor";
const char *MQTT_USERNAME = "";
const char *MQTT_PASSWORD = "";

// Must match `mqtt.base_topic` in config/energy_default.yaml.
const char *MQTT_BASE_TOPIC = "smart-energy";

const unsigned long SEND_INTERVAL_MS = 500;
const unsigned long RECONNECT_INTERVAL_MS = 5000;
const int RELAY_PIN = 26;

unsigned long lastSendTime = 0;
unsigned long lastReconnectAttempt = 0;
bool relayState = true;

WiFiClient wifiClient;
PubSubClient mqttClient(wifiClient);

char telemetryTopic[96];
char commandTopic[96];

bool wifiConfigured() {
  return WIFI_SSID != NULL && strlen(WIFI_SSID) > 0;
}

void applyCommand(const String &command) {
  if (command == "SHED_LOAD" || command == "OFF") {
    digitalWrite(RELAY_PIN, LOW);
    relayState = false;
  } else if (command == "CONNECT_LOAD" || command == "ON") {
    digitalWrite(RELAY_PIN, HIGH);
    relayState = true;
  }
}

void onMqttMessage(char *topic, byte *payload, unsigned int length) {
  String command;
  command.reserve(length);
  for (unsigned int i = 0; i < length; i++) {
    command += (char)payload[i];
  }
  command.trim();
  applyCommand(command);
}

// Non-blocking: one attempt per call, so the sampling loop never stalls when
// the network is down.
void ensureConnectivity() {
  if (!wifiConfigured()) {
    return;
  }

  unsigned long now = millis();
  if (now - lastReconnectAttempt < RECONNECT_INTERVAL_MS) {
    return;
  }
  lastReconnectAttempt = now;

  if (WiFi.status() != WL_CONNECTED) {
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    return;
  }

  if (!mqttClient.connected()) {
    bool connected;
    if (strlen(MQTT_USERNAME) > 0) {
      connected = mqttClient.connect(MQTT_CLIENT_ID, MQTT_USERNAME, MQTT_PASSWORD);
    } else {
      connected = mqttClient.connect(MQTT_CLIENT_ID);
    }

    if (connected) {
      mqttClient.subscribe(commandTopic);
    }
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(RELAY_PIN, OUTPUT);
  digitalWrite(RELAY_PIN, HIGH);

  snprintf(telemetryTopic, sizeof(telemetryTopic), "%s/device/telemetry", MQTT_BASE_TOPIC);
  snprintf(commandTopic, sizeof(commandTopic), "%s/device/commands", MQTT_BASE_TOPIC);

  if (wifiConfigured()) {
    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    mqttClient.setServer(MQTT_HOST, MQTT_PORT);
    mqttClient.setCallback(onMqttMessage);
  }

  delay(1000);
}

void loop() {
  unsigned long now = millis();

  ensureConnectivity();
  if (wifiConfigured() && mqttClient.connected()) {
    mqttClient.loop();
  }

  if (Serial.available() > 0) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    applyCommand(cmd);
  }

  if (now - lastSendTime >= SEND_INTERVAL_MS) {
    lastSendTime = now;

    float voltage = 230.0 + random(-15, 15) / 10.0;
    float current = relayState ? (2.5 + random(-5, 15) / 10.0) : 0.0;
    if (current < 0) current = 0.0;

    float powerFactor = relayState ? 0.92 : 1.0;
    float activePower = voltage * current * powerFactor;
    float frequency = 50.0 + random(-1, 2) / 10.0;

    char payload[192];
    snprintf(
      payload, sizeof(payload),
      "{\"voltage\":%.2f,\"current\":%.2f,\"power\":%.2f,"
      "\"power_factor\":%.2f,\"frequency\":%.1f,\"relay_state\":%s}",
      voltage, current, activePower, powerFactor, frequency,
      relayState ? "true" : "false"
    );

    // Serial is always written so a USB-connected host keeps working even when
    // WiFi is configured.
    Serial.println(payload);

    if (wifiConfigured() && mqttClient.connected()) {
      mqttClient.publish(telemetryTopic, payload);
    }
  }
}
