# IoT Smart Energy Monitoring System ⚡

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![Hardware Support](https://img.shields.io/badge/hardware-ESP32%20%7C%20Arduino-teal.svg)](hardware/esp32_energy_monitor/esp32_energy_monitor.ino)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Build Status](https://img.shields.io/badge/build-passing-brightgreen.svg)]()

An enterprise-grade physical and software IoT energy monitoring engineering system designed for real-time AC electrical energy data acquisition, power vector processing, anomaly detection, asynchronous database logging, and live web visualization.

---

## 🌟 Architecture & Key Features

- ⚡ **Physical Hardware Firmware**: ESP32 C++ firmware (`hardware/esp32_energy_monitor/esp32_energy_monitor.ino`) transmitting structured JSON sensor telemetry over Serial (`115200` baud) or WiFi.
- 🔌 **Hardware Telemetry Ingestion Bridge**: Python receiver pipeline (`smart_energy/hardware_bridge.py`) reading physical sensor data with a high-fidelity synthetic hardware emulator fallback.
- 📐 **Electrical Analytics Engine**: Computes Active Power ($P = V \times I \times PF$), Apparent Power ($S = V \times I$), Reactive Power ($Q = \sqrt{S^2 - P^2}$), Cumulative Energy ($kWh$), and Energy Cost ($).
- 🚨 **Automated Anomaly Detection**:
  - Consumption Surge / Spike Alerts ($P \ge 2.5\text{ kW}$)
  - Voltage Sag ($V < 207\text{V}$) & Swell ($V > 253\text{V}$) Detection
  - Low Power Factor Warning ($PF < 0.85$)
- 📊 **Asynchronous SQLite WAL Storage**: Non-blocking SQLite event logging with Write-Ahead Logging (WAL) and indexed analytical queries.
- 🌐 **Interactive Web Dashboard**: Embedded server serving a real-time web dashboard on `http://localhost:8050` with live gauges, timeline charts, and alert feeds.

---

## 🛠️ Hardware Setup & Circuit Schematic

See the complete physical circuit schematic, component list, and safety guide in [`docs/iot_energy_hardware_guide.md`](docs/iot_energy_hardware_guide.md).

```text
AC Mains 220V/110V  ---> [ PZEM-004T / CT Sensor ] ---> ESP32 Microcontroller
                                                                  |
                                                     [ USB Serial / WiFi JSON ]
                                                                  |
                                                     Python Hardware Bridge
                                                                  |
                                                  Real-Time Web Dashboard (8050)
```

---

## 🚀 Quick Start

### Installation

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
python -m pip install -e .
```

### Usage Commands

Launch live energy monitoring & web dashboard:

```powershell
smart-energy run
```
*Access live dashboard at `http://localhost:8050`.*

Display configuration diagnostics:

```powershell
smart-energy status
```

Fetch recent historical telemetry logs:

```powershell
smart-energy report --limit 20
```

---

## 🧪 Testing

Execute automated unit test suite:

```powershell
pytest tests/ -v
```

---

## 📄 License

Distributed under the MIT License. See [LICENSE](LICENSE) for details.
