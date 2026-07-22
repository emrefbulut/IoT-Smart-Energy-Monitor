from __future__ import annotations

import argparse
import logging
from pathlib import Path
import sys
import time

from .analytics import EnergyAnalyticsEngine
from .config import load_energy_settings
from .database import AsyncEnergyDB
from .dashboard import EnergyDashboardServer
from .hardware_bridge import IoTDataReceiver

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("smart_energy.cli")


def print_status(config_path: str = "config/energy_default.yaml") -> None:
    print("\n==================================================")
    print("   IoT SMART ENERGY MONITORING SYSTEM DIAGNOSTICS ")
    print("==================================================\n")
    
    settings = load_energy_settings(config_path)
    
    print(f"Config File         : {config_path}")
    print(f"Target Serial Port  : {settings.hardware.port or 'Auto / Emulator'}")
    print(f"Sampling Rate       : {settings.hardware.sampling_interval_seconds}s")
    print(f"Nominal Grid Voltage: {settings.grid.nominal_voltage}V AC")
    print(f"Voltage Sag Limit   : {settings.grid.voltage_sag_threshold}V")
    print(f"Voltage Swell Limit : {settings.grid.voltage_swell_threshold}V")
    print(f"Spike Threshold     : {settings.grid.spike_power_threshold_kw} kW")
    print(f"Base Rate ($/kWh)   : ${settings.grid.cost_per_kwh}")
    print(f"Database Path       : {settings.storage.sqlite_path}")
    print(f"Web Dashboard Port  : http://localhost:{settings.dashboard.port}")
    print("==================================================\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="smart-energy",
        description="IoT Smart Energy Monitoring System - Energy Analytics & Telemetry Engine.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="Run energy monitoring backend and dashboard")
    run.add_argument("--config", default="config/energy_default.yaml")
    run.add_argument("--port", help="Serial COM port (e.g. COM3 or /dev/ttyUSB0)")
    run.add_argument("--web-port", type=int, default=8050)
    run.add_argument("--no-web", action="store_true")

    status = subparsers.add_parser("status", help="Show system configuration status")
    status.add_argument("--config", default="config/energy_default.yaml")

    report = subparsers.add_parser("report", help="Fetch recent stored telemetry logs")
    report.add_argument("--config", default="config/energy_default.yaml")
    report.add_argument("--limit", type=int, default=20)

    export_csv = subparsers.add_parser("export-csv", help="Export telemetry logs to CSV file")
    export_csv.add_argument("--config", default="config/energy_default.yaml")
    export_csv.add_argument("--output", default="logs/energy_report.csv")
    export_csv.add_argument("--limit", type=int, default=1000)

    args = parser.parse_args(argv)

    if args.command == "status":
        print_status(config_path=args.config)
        return 0

    if args.command == "report":
        settings = load_energy_settings(args.config)
        db = AsyncEnergyDB(settings.storage)
        time.sleep(0.5)
        rows = db.fetch_recent(limit=args.limit)
        print(f"\n--- RECENT ENERGY TELEMETRY LOGS ({len(rows)} entries) ---")
        for r in rows:
            print(f"[{r['datetime_str']}] {r['voltage']}V | {r['current']}A | {r['active_power']}W | Tariff: {r.get('tariff_tier', 'OFF_PEAK')} | {r['cumulative_kwh']} kWh (${r['estimated_cost']})")
        db.close()
        return 0

    if args.command == "export-csv":
        settings = load_energy_settings(args.config)
        db = AsyncEnergyDB(settings.storage)
        time.sleep(0.5)
        target = db.export_csv(output_file=args.output, limit=args.limit)
        print(f"Successfully exported energy telemetry report to: {target}")
        db.close()
        return 0

    if args.command == "run":
        settings = load_energy_settings(args.config)
        if args.port:
            settings.hardware.port = args.port

        receiver = IoTDataReceiver(settings.hardware)
        analytics = EnergyAnalyticsEngine(settings.grid)
        db = AsyncEnergyDB(settings.storage)

        dashboard = None
        if not args.no_web:
            port = args.web_port or settings.dashboard.port
            dashboard = EnergyDashboardServer(settings.dashboard)
            dashboard.start()

        def on_sample(raw_sample):
            telemetry = analytics.process_sample(raw_sample)
            db.record(telemetry)
            if dashboard is not None:
                dashboard.state.update(telemetry)
            if telemetry.anomalies:
                logger.warning(f"GRID ANOMALY DETECTED: {', '.join(telemetry.anomalies)}")

        receiver.subscribe(on_sample)
        receiver.start()

        print("\n==================================================")
        print("  IoT SMART ENERGY MONITORING SYSTEM RUNNING      ")
        print(f"  Live Dashboard: http://localhost:{args.web_port or settings.dashboard.port} ")
        print("  Press Ctrl+C to stop                            ")
        print("==================================================\n")

        try:
            while True:
                time.sleep(1.0)
        except KeyboardInterrupt:
            print("\nShutting down energy monitoring engine...")
        finally:
            receiver.stop()
            db.close()
            if dashboard is not None:
                dashboard.stop()

        return 0

    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    sys.exit(main())
