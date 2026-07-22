from __future__ import annotations

import json
import logging
import queue
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from .analytics import EnergyTelemetry, export_telemetry_to_csv
from .config import StorageConfig

logger = logging.getLogger("smart_energy.database")


class AsyncEnergyDB:
    """Asynchronous SQLite storage engine for energy telemetry and anomaly events with WAL mode."""

    def __init__(self, config: StorageConfig):
        self.config = config
        self.db_path = Path(config.sqlite_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._queue: queue.Queue[EnergyTelemetry] = queue.Queue()
        self._stopped = threading.Event()
        self._worker = threading.Thread(target=self._process_queue, daemon=True)

        self._init_db()
        self._worker.start()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            if self.config.wal_mode:
                conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS energy_telemetry (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    datetime_str TEXT NOT NULL,
                    voltage REAL NOT NULL,
                    current REAL NOT NULL,
                    active_power REAL NOT NULL,
                    apparent_power REAL NOT NULL,
                    reactive_power REAL NOT NULL,
                    power_factor REAL NOT NULL,
                    frequency REAL NOT NULL,
                    cumulative_kwh REAL NOT NULL,
                    estimated_cost REAL NOT NULL,
                    tariff_tier TEXT NOT NULL DEFAULT 'OFF_PEAK',
                    anomalies_json TEXT,
                    is_simulated INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_energy_ts ON energy_telemetry(timestamp);"
            )
            conn.commit()

    def record(self, telemetry: EnergyTelemetry) -> None:
        self._queue.put(telemetry)

    def _process_queue(self) -> None:
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        try:
            while not self._stopped.is_set() or not self._queue.empty():
                try:
                    t = self._queue.get(timeout=0.5)
                except queue.Empty:
                    continue

                dt_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t.timestamp))
                anomalies_json = json.dumps(list(t.anomalies))

                conn.execute(
                    """
                    INSERT INTO energy_telemetry (
                        timestamp, datetime_str, voltage, current, active_power,
                        apparent_power, reactive_power, power_factor, frequency,
                        cumulative_kwh, estimated_cost, tariff_tier, anomalies_json, is_simulated
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        t.timestamp,
                        dt_str,
                        t.voltage,
                        t.current,
                        t.active_power,
                        t.apparent_power,
                        t.reactive_power,
                        t.power_factor,
                        t.frequency,
                        t.cumulative_kwh,
                        t.estimated_cost,
                        t.tariff_tier,
                        anomalies_json,
                        1 if t.is_simulated else 0,
                    ),
                )
                conn.commit()
                self._queue.task_done()
        finally:
            conn.close()

    def fetch_recent(self, limit: int = 50) -> list[dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT timestamp, datetime_str, voltage, current, active_power,
                       apparent_power, reactive_power, power_factor, frequency,
                       cumulative_kwh, estimated_cost, tariff_tier, anomalies_json, is_simulated
                FROM energy_telemetry
                ORDER BY id DESC LIMIT ?
                """,
                (limit,),
            )
            rows = cursor.fetchall()
            return [dict(r) for r in rows]

    def export_csv(self, output_file: str | Path, limit: int = 1000) -> Path:
        rows = self.fetch_recent(limit=limit)
        return export_telemetry_to_csv(rows, output_file)

    def close(self) -> None:
        self._stopped.set()
        if self._worker.is_alive():
            self._worker.join(timeout=2.0)
