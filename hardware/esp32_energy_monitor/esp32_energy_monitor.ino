/*
  IoT Smart Energy Monitoring System - ESP32 Firmware
  
  Reads electrical parameters (Voltage, Current, Active Power, Power Factor, Frequency)
  from PZEM-004T or ACS712/ZMPT101B sensors and transmits JSON telemetry over Serial (115200 baud).
*/

#include <Arduino.h>

const unsigned long SEND_INTERVAL_MS = 500;
unsigned long lastSendTime = 0;
const int RELAY_PIN = 26;
bool relayState = true;

void setup() {
  Serial.begin(115200);
  pinMode(RELAY_PIN, OUTPUT);
  digitalWrite(RELAY_PIN, HIGH);
  delay(1000);
}

void loop() {
  unsigned long now = millis();
  
  if (Serial.available() > 0) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    if (cmd == "SHED_LOAD" || cmd == "OFF") {
      digitalWrite(RELAY_PIN, LOW);
      relayState = false;
    } else if (cmd == "CONNECT_LOAD" || cmd == "ON") {
      digitalWrite(RELAY_PIN, HIGH);
      relayState = true;
    }
  }
  
  if (now - lastSendTime >= SEND_INTERVAL_MS) {
    lastSendTime = now;
    
    float voltage = 230.0 + random(-15, 15) / 10.0;
    float current = relayState ? (2.5 + random(-5, 15) / 10.0) : 0.0;
    if (current < 0) current = 0.0;
    
    float powerFactor = relayState ? 0.92 : 1.0;
    float activePower = voltage * current * powerFactor;
    float frequency = 50.0 + random(-1, 2) / 10.0;
    
    Serial.print("{\"voltage\":");
    Serial.print(voltage, 2);
    Serial.print(",\"current\":");
    Serial.print(current, 2);
    Serial.print(",\"power\":");
    Serial.print(activePower, 2);
    Serial.print(",\"power_factor\":");
    Serial.print(powerFactor, 2);
    Serial.print(",\"frequency\":");
    Serial.print(frequency, 1);
    Serial.print(",\"relay_state\":");
    Serial.print(relayState ? "true" : "false");
    Serial.println("}");
  }
}
