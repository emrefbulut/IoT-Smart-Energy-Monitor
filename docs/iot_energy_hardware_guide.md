# Physical Hardware Wiring & Calibration Guide ⚡

This document details the physical hardware design, sensor connections, and safety procedures for the **IoT Smart Energy Monitoring System**.

---

## 🛠️ Hardware Components List

| Component | Function | Model / Spec |
| :--- | :--- | :--- |
| **Microcontroller** | Sensor data acquisition & JSON output | ESP32 NodeMCU / Arduino Uno |
| **Power Meter Sensor** | AC Voltage, Current, Power & PF Measurement | PZEM-004T v3.0 (Optocoupler Isolated) |
| **Alternative Current Sensor** | Hall Effect Current Measurement | ACS712-30A / CT Transformer SCT-013 |
| **Alternative Voltage Sensor** | Voltage Transformer Module | ZMPT101B |
| **Relay Module** | Remote Load Shedding / Overload Disconnect | 1-Channel 5V/10A Relay |

---

## ⚡ Circuit Schematic & Pin Wiring

### ESP32 to PZEM-004T v3.0 Pin Connections

```text
ESP32 Pin          PZEM-004T v3.0 Pin
----------         ------------------
5V             --> VCC (5V)
GND            --> GND
GPIO 16 (RX2)  --> TX
GPIO 17 (TX2)  --> RX
```

---

## 💻 Communication Protocol

The hardware firmware outputs structured JSON packets over USB Serial at **115200 baud**:

```json
{
  "voltage": 231.40,
  "current": 4.12,
  "power": 875.20,
  "power_factor": 0.92,
  "frequency": 50.0,
  "relay_state": true
}
```
