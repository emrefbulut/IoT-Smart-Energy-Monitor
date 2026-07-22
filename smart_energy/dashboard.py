from __future__ import annotations

from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import logging
import socketserver
import threading
import time
from typing import Any

from .analytics import EnergyTelemetry
from .config import DashboardConfig

logger = logging.getLogger("smart_energy.dashboard")


class DashboardState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.latest_telemetry: dict[str, Any] = {
            "system": "IoT Smart Energy Monitoring System",
            "voltage": 230.0,
            "current": 0.0,
            "active_power": 0.0,
            "apparent_power": 0.0,
            "reactive_power": 0.0,
            "power_factor": 1.0,
            "frequency": 50.0,
            "cumulative_kwh": 0.0,
            "estimated_cost": 0.0,
            "anomalies": [],
            "is_simulated": True,
            "timestamp": time.time(),
        }
        self.history: list[dict[str, Any]] = []

    def update(self, telemetry: EnergyTelemetry) -> None:
        with self.lock:
            data = {
                "voltage": telemetry.voltage,
                "current": telemetry.current,
                "active_power": telemetry.active_power,
                "apparent_power": telemetry.apparent_power,
                "reactive_power": telemetry.reactive_power,
                "power_factor": telemetry.power_factor,
                "frequency": telemetry.frequency,
                "cumulative_kwh": telemetry.cumulative_kwh,
                "estimated_cost": telemetry.estimated_cost,
                "anomalies": list(telemetry.anomalies),
                "is_simulated": telemetry.is_simulated,
                "timestamp": telemetry.timestamp,
                "datetime": time.strftime("%H:%M:%S", time.localtime(telemetry.timestamp)),
            }
            self.latest_telemetry.update(data)
            self.history.append(data)
            if len(self.history) > 100:
                self.history.pop(0)


class EnergyDashboardHandler(BaseHTTPRequestHandler):
    state: DashboardState | None = None

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>IoT Smart Energy Monitoring System</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #0b132b; color: #f8fafc; margin: 0; padding: 20px; }
        header { display: flex; justify-content: space-between; align-items: center; border-bottom: 2px solid #1c2541; padding-bottom: 15px; margin-bottom: 25px; }
        h1 { color: #48cae4; margin: 0; font-size: 1.8rem; }
        .badge { background: #1c2541; color: #90e0ef; padding: 6px 12px; border-radius: 20px; font-size: 0.85rem; border: 1px solid #3a506b; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 20px; margin-bottom: 25px; }
        .card { background: #1c2541; border-radius: 12px; padding: 20px; border: 1px solid #3a506b; box-shadow: 0 8px 20px rgba(0,0,0,0.3); }
        .card-title { font-size: 0.85rem; color: #90e0ef; text-transform: uppercase; letter-spacing: 1px; }
        .card-val { font-size: 2.2rem; font-weight: bold; margin-top: 8px; color: #ffffff; }
        .card-unit { font-size: 1rem; color: #6fffe9; font-weight: normal; }
        .chart-container { background: #1c2541; border-radius: 12px; padding: 20px; border: 1px solid #3a506b; margin-bottom: 25px; }
        .anomaly-card { background: #2b1d28; border: 1px solid #f72585; border-radius: 12px; padding: 20px; }
        .anomaly-title { color: #f72585; font-weight: bold; margin-bottom: 10px; }
        .anomaly-list { font-family: monospace; font-size: 0.9rem; color: #ffb703; max-height: 120px; overflow-y: auto; }
    </style>
</head>
<body>
    <header>
        <div>
            <h1>⚡ IoT Smart Energy Monitor</h1>
            <div style="color: #94a3b8; font-size: 0.9rem; margin-top: 4px;">Real-Time Electrical Power & Sensor Analytics</div>
        </div>
        <div id="source-badge" class="badge">Hardware Bridge: Connecting...</div>
    </header>

    <div class="grid">
        <div class="card">
            <div class="card-title">Voltage (RMS)</div>
            <div class="card-val" id="val-v">0.0 <span class="card-unit">V</span></div>
        </div>
        <div class="card">
            <div class="card-title">Current (RMS)</div>
            <div class="card-val" id="val-i">0.0 <span class="card-unit">A</span></div>
        </div>
        <div class="card">
            <div class="card-title">Active Power</div>
            <div class="card-val" id="val-p">0.0 <span class="card-unit">W</span></div>
        </div>
        <div class="card">
            <div class="card-title">Power Factor</div>
            <div class="card-val" id="val-pf">0.00 <span class="card-unit">PF</span></div>
        </div>
        <div class="card">
            <div class="card-title">Cumulative Energy</div>
            <div class="card-val" id="val-kwh">0.0000 <span class="card-unit">kWh</span></div>
        </div>
        <div class="card">
            <div class="card-title">Estimated Cost</div>
            <div class="card-val" id="val-cost">$0.00 <span class="card-unit">USD</span></div>
        </div>
    </div>

    <div class="chart-container">
        <canvas id="powerChart" height="90"></canvas>
    </div>

    <div class="anomaly-card">
        <div class="anomaly-title">🚨 System Alerts & Anomaly Feed</div>
        <div class="anomaly-list" id="alert-feed">System Operating Normally - No Anomalies Detected</div>
    </div>

    <script>
        const ctx = document.getElementById('powerChart').getContext('2d');
        const powerChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: [],
                datasets: [{
                    label: 'Active Power (Watts)',
                    data: [],
                    borderColor: '#48cae4',
                    backgroundColor: 'rgba(72, 202, 228, 0.1)',
                    borderWidth: 2,
                    fill: true,
                    tension: 0.3
                }]
            },
            options: {
                responsive: true,
                scales: {
                    x: { grid: { color: '#2b3a55' }, ticks: { color: '#90e0ef' } },
                    y: { grid: { color: '#2b3a55' }, ticks: { color: '#90e0ef' } }
                },
                plugins: { legend: { labels: { color: '#f8fafc' } } }
            }
        });

        async function updateDashboard() {
            try {
                const res = await fetch('/api/energy/live');
                const data = await res.json();
                
                document.getElementById('val-v').innerHTML = `${data.voltage.toFixed(1)} <span class="card-unit">V</span>`;
                document.getElementById('val-i').innerHTML = `${data.current.toFixed(2)} <span class="card-unit">A</span>`;
                document.getElementById('val-p').innerHTML = `${data.active_power.toFixed(1)} <span class="card-unit">W</span>`;
                document.getElementById('val-pf').innerHTML = `${data.power_factor.toFixed(2)} <span class="card-unit">PF</span>`;
                document.getElementById('val-kwh').innerHTML = `${data.cumulative_kwh.toFixed(4)} <span class="card-unit">kWh</span>`;
                document.getElementById('val-cost').innerHTML = `$${data.estimated_cost.toFixed(4)} <span class="card-unit">USD</span>`;
                
                document.getElementById('source-badge').textContent = data.is_simulated ? "Mode: Hardware Emulator Stream" : "Mode: Physical ESP32 Sensor Connected";

                const historyRes = await fetch('/api/energy/history');
                const history = await historyRes.json();
                
                powerChart.data.labels = history.map(h => h.datetime);
                powerChart.data.datasets[0].data = history.map(h => h.active_power);
                powerChart.update('none');

                const alertFeed = document.getElementById('alert-feed');
                if (data.anomalies && data.anomalies.length > 0) {
                    alertFeed.innerHTML = data.anomalies.map(a => `[${data.datetime}] WARNING: ${a}`).join('<br>');
                } else {
                    alertFeed.textContent = "System Operating Normally - Grid Voltage & Power Factor Within Limits";
                }
            } catch(e) {}
        }
        setInterval(updateDashboard, 500);
    </script>
</body>
</html>"""
            self.wfile.write(html.encode("utf-8"))
            return

        if self.path == "/api/energy/live":
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            if self.state:
                with self.state.lock:
                    data = dict(self.state.latest_telemetry)
            else:
                data = {"error": "no state"}
            self.wfile.write(json.dumps(data).encode("utf-8"))
            return

        if self.path == "/api/energy/history":
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            if self.state:
                with self.state.lock:
                    data = list(self.state.history)
            else:
                data = []
            self.wfile.write(json.dumps(data).encode("utf-8"))
            return

        self.send_error(404, "Not Found")


class EnergyDashboardServer:
    def __init__(self, config: DashboardConfig):
        self.config = config
        self.state = DashboardState()
        self.server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        class CustomHandler(EnergyDashboardHandler):
            state = self.state

        self.server = socketserver.TCPServer((self.config.host, self.config.port), CustomHandler, bind_and_activate=False)
        self.server.allow_reuse_address = True
        self.server.server_bind()
        self.server.server_activate()

        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self._thread.start()
        logger.info(f"Energy Web Dashboard live at http://localhost:{self.config.port}")

    def stop(self) -> None:
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
