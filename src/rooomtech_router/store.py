"""SQLite persistence for route receipts, feedback, learning, and exact cache."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any


class RouterStore:
    def __init__(self, path: str) -> None:
        self.path = path
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._initialize()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _initialize(self) -> None:
        with self._lock:
            if self.path != ":memory:":
                self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS routes (
                    route_id TEXT PRIMARY KEY,
                    created_at INTEGER NOT NULL,
                    tenant_id TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    topology TEXT NOT NULL,
                    status TEXT NOT NULL,
                    selected_models_json TEXT NOT NULL,
                    plan_json TEXT NOT NULL,
                    receipt_json TEXT NOT NULL,
                    receipt_sha256 TEXT NOT NULL,
                    receipt_signature TEXT,
                    actual_cost_usd REAL NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    route_id TEXT NOT NULL,
                    model_id TEXT,
                    reward REAL NOT NULL,
                    category TEXT,
                    created_at INTEGER NOT NULL,
                    FOREIGN KEY(route_id) REFERENCES routes(route_id)
                );

                CREATE TABLE IF NOT EXISTS model_stats (
                    model_id TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    reward_sum REAL NOT NULL DEFAULT 0,
                    feedback_trials INTEGER NOT NULL DEFAULT 0,
                    success_calls INTEGER NOT NULL DEFAULT 0,
                    failure_calls INTEGER NOT NULL DEFAULT 0,
                    latency_ewma REAL,
                    PRIMARY KEY(model_id, task_type)
                );

                CREATE TABLE IF NOT EXISTS response_cache (
                    cache_key TEXT PRIMARY KEY,
                    response_json TEXT NOT NULL,
                    expires_at INTEGER NOT NULL
                );
                """
            )
            self._conn.commit()

    def model_stats(self, model_id: str, task_type: str) -> dict[str, float]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM model_stats WHERE model_id=? AND task_type=?",
                (model_id, task_type),
            ).fetchone()
        if row is None:
            return {
                "reward_sum": 0.0,
                "feedback_trials": 0.0,
                "success_calls": 0.0,
                "failure_calls": 0.0,
                "latency_ewma": 0.0,
            }
        return {key: float(row[key] or 0) for key in row.keys() if key not in {"model_id", "task_type"}}

    def total_feedback_trials(self, task_type: str) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COALESCE(SUM(feedback_trials), 0) AS total FROM model_stats WHERE task_type=?",
                (task_type,),
            ).fetchone()
        return int(row["total"])

    def record_provider_result(
        self, model_id: str, task_type: str, *, success: bool, latency_ms: int
    ) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO model_stats (
                    model_id, task_type, success_calls, failure_calls, latency_ewma
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(model_id, task_type) DO UPDATE SET
                    success_calls = success_calls + excluded.success_calls,
                    failure_calls = failure_calls + excluded.failure_calls,
                    latency_ewma = CASE
                        WHEN model_stats.latency_ewma IS NULL THEN excluded.latency_ewma
                        ELSE 0.8 * model_stats.latency_ewma + 0.2 * excluded.latency_ewma
                    END
                """,
                (model_id, task_type, int(success), int(not success), float(latency_ms)),
            )
            self._conn.commit()

    def save_route(
        self,
        *,
        route_id: str,
        tenant_id: str,
        request_hash: str,
        task_type: str,
        topology: str,
        status: str,
        selected_models: list[str],
        plan: dict[str, Any],
        receipt: dict[str, Any],
        receipt_sha256: str,
        receipt_signature: str | None,
        actual_cost_usd: float,
    ) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO routes (
                    route_id, created_at, tenant_id, request_hash, task_type,
                    topology, status, selected_models_json, plan_json, receipt_json,
                    receipt_sha256, receipt_signature, actual_cost_usd
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    route_id,
                    int(time.time()),
                    tenant_id,
                    request_hash,
                    task_type,
                    topology,
                    status,
                    json.dumps(selected_models, ensure_ascii=False),
                    json.dumps(plan, ensure_ascii=False, sort_keys=True),
                    json.dumps(receipt, ensure_ascii=False, sort_keys=True),
                    receipt_sha256,
                    receipt_signature,
                    actual_cost_usd,
                ),
            )
            self._conn.commit()

    def get_route(self, route_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM routes WHERE route_id=?", (route_id,)
            ).fetchone()
        if row is None:
            return None
        return {
            "route_id": row["route_id"],
            "created_at": row["created_at"],
            "tenant_id": row["tenant_id"],
            "request_hash": row["request_hash"],
            "task_type": row["task_type"],
            "topology": row["topology"],
            "status": row["status"],
            "selected_models": json.loads(row["selected_models_json"]),
            "plan": json.loads(row["plan_json"]),
            "receipt": json.loads(row["receipt_json"]),
            "receipt_sha256": row["receipt_sha256"],
            "receipt_signature": row["receipt_signature"],
            "actual_cost_usd": row["actual_cost_usd"],
        }

    def add_feedback(
        self,
        route_id: str,
        reward: float,
        *,
        model_id: str | None = None,
        category: str | None = None,
    ) -> list[str]:
        reward = min(1.0, max(0.0, float(reward)))
        route = self.get_route(route_id)
        if route is None:
            raise KeyError(route_id)
        model_ids = [model_id] if model_id else list(route["selected_models"])
        with self._lock:
            self._conn.execute(
                "INSERT INTO feedback (route_id, model_id, reward, category, created_at) VALUES (?, ?, ?, ?, ?)",
                (route_id, model_id, reward, category, int(time.time())),
            )
            for selected in model_ids:
                self._conn.execute(
                    """
                    INSERT INTO model_stats (
                        model_id, task_type, reward_sum, feedback_trials
                    ) VALUES (?, ?, ?, 1)
                    ON CONFLICT(model_id, task_type) DO UPDATE SET
                        reward_sum = reward_sum + excluded.reward_sum,
                        feedback_trials = feedback_trials + 1
                    """,
                    (selected, route["task_type"], reward),
                )
            self._conn.commit()
        return model_ids

    def cache_get(self, cache_key: str) -> dict[str, Any] | None:
        now = int(time.time())
        with self._lock:
            row = self._conn.execute(
                "SELECT response_json, expires_at FROM response_cache WHERE cache_key=?",
                (cache_key,),
            ).fetchone()
            if row is None:
                return None
            if row["expires_at"] < now:
                self._conn.execute("DELETE FROM response_cache WHERE cache_key=?", (cache_key,))
                self._conn.commit()
                return None
        return json.loads(row["response_json"])

    def cache_put(self, cache_key: str, response: dict[str, Any], ttl_seconds: int) -> None:
        if ttl_seconds <= 0:
            return
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO response_cache (cache_key, response_json, expires_at) VALUES (?, ?, ?)",
                (
                    cache_key,
                    json.dumps(response, ensure_ascii=False, sort_keys=True),
                    int(time.time()) + ttl_seconds,
                ),
            )
            self._conn.commit()

