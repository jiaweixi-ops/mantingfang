from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from .models import ActionStatus, Goal, MajorEvent, Observation, PlannedAction, utc_now


class SQLiteStore:
    """Durable local state with an append-only audit trail."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._init_schema()

    def close(self) -> None:
        self._conn.close()

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS observations (
                id TEXT PRIMARY KEY, observed_at TEXT NOT NULL, source TEXT NOT NULL,
                region TEXT, confidence REAL, data_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS goals (
                id TEXT PRIMARY KEY, created_at TEXT NOT NULL, completed_at TEXT,
                level TEXT NOT NULL, status TEXT NOT NULL, title TEXT NOT NULL, target_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS actions (
                id TEXT PRIMARY KEY, created_at TEXT NOT NULL, action_type TEXT NOT NULL,
                risk TEXT NOT NULL, idempotency_key TEXT NOT NULL UNIQUE, status TEXT NOT NULL,
                payload_json TEXT NOT NULL, result_json TEXT
            );
            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY, created_at TEXT NOT NULL, severity TEXT NOT NULL,
                title TEXT NOT NULL, body TEXT NOT NULL, requires_decision INTEGER NOT NULL,
                screenshot_path TEXT, delivered_at TEXT
            );
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
                category TEXT NOT NULL, message TEXT NOT NULL, details_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS runtime_state (
                key TEXT PRIMARY KEY, value_json TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS token_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT, recorded_at TEXT NOT NULL,
                kind TEXT NOT NULL, model TEXT NOT NULL,
                prompt_tokens INTEGER NOT NULL, completion_tokens INTEGER NOT NULL,
                total_tokens INTEGER NOT NULL
            );
            """
        )
        self._conn.commit()

    def _commit(self) -> None:
        self._conn.commit()

    def set_runtime(self, key: str, value: Any) -> None:
        self._conn.execute(
            "INSERT INTO runtime_state(key, value_json, updated_at) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at",
            (key, json.dumps(value, ensure_ascii=False), utc_now()),
        )
        self._commit()

    def get_runtime(self, key: str, default: Any = None) -> Any:
        row = self._conn.execute("SELECT value_json FROM runtime_state WHERE key=?", (key,)).fetchone()
        return default if row is None else json.loads(row["value_json"])

    def add_observation(self, observation: Observation) -> None:
        self._conn.execute(
            "INSERT INTO observations(id, observed_at, source, region, confidence, data_json) VALUES(?,?,?,?,?,?)",
            (observation.id, observation.observed_at, observation.source, observation.region, observation.confidence,
             json.dumps(observation.data, ensure_ascii=False)),
        )
        self.audit("observation", "observation recorded", {"id": observation.id, "region": observation.region})
        self._commit()

    def record_token_usage(self, usage: dict[str, Any]) -> None:
        self._conn.execute(
            "INSERT INTO token_usage(recorded_at, kind, model, prompt_tokens, completion_tokens, total_tokens) VALUES(?,?,?,?,?,?)",
            (utc_now(), str(usage.get("kind", "chat")), str(usage.get("model", "unknown")),
             int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0)), int(usage.get("total_tokens", 0))),
        )
        self.audit("token_usage", "DeepSeek usage recorded", usage)
        self._commit()

    def token_usage_totals(self) -> dict[str, int]:
        row = self._conn.execute(
            "SELECT COALESCE(SUM(prompt_tokens),0) AS prompt_tokens, "
            "COALESCE(SUM(completion_tokens),0) AS completion_tokens, "
            "COALESCE(SUM(total_tokens),0) AS total_tokens FROM token_usage"
        ).fetchone()
        return {key: int(row[key]) for key in ("prompt_tokens", "completion_tokens", "total_tokens")}

    def latest_observation(self) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT * FROM observations ORDER BY observed_at DESC, rowid DESC LIMIT 1").fetchone()
        if row is None:
            return None
        return {**dict(row), "data": json.loads(row["data_json"])}

    def add_goal(self, goal: Goal) -> None:
        self._conn.execute(
            "INSERT INTO goals(id, created_at, completed_at, level, status, title, target_json) VALUES(?,?,?,?,?,?,?)",
            (goal.id, goal.created_at, goal.completed_at, goal.level, goal.status, goal.title,
             json.dumps(goal.target, ensure_ascii=False)),
        )
        self.audit("goal", "goal created", goal.to_dict())
        self._commit()

    def replace_active_long_term_goal(self, goal: Goal) -> None:
        self._conn.execute("UPDATE goals SET status='superseded', completed_at=? WHERE level='long-term' AND status='active'", (utc_now(),))
        self.add_goal(goal)

    def active_goals(self) -> list[dict[str, Any]]:
        rows = self._conn.execute("SELECT * FROM goals WHERE status='active' ORDER BY created_at").fetchall()
        return [{**dict(row), "target": json.loads(row["target_json"])} for row in rows]

    def record_action(self, action: PlannedAction, status: ActionStatus, result: dict[str, Any] | None = None, *, idempotency_key: str | None = None) -> bool:
        action_key = idempotency_key or action.key()
        try:
            self._conn.execute(
                "INSERT INTO actions(id, created_at, action_type, risk, idempotency_key, status, payload_json, result_json) VALUES(?,?,?,?,?,?,?,?)",
                (action.id, utc_now(), action.action_type, action.risk.value, action_key, status.value,
                 json.dumps(action.payload, ensure_ascii=False), json.dumps(result, ensure_ascii=False) if result is not None else None),
            )
        except sqlite3.IntegrityError:
            existing = self._conn.execute("SELECT id FROM actions WHERE idempotency_key=?", (action_key,)).fetchone()
            if existing is None or existing["id"] != action.id:
                return False
            self._conn.execute(
                "UPDATE actions SET status=?, result_json=? WHERE id=?",
                (status.value, json.dumps(result, ensure_ascii=False) if result is not None else None, action.id),
            )
        self.audit("action", f"action {status.value}", {"id": action.id, "key": action_key, "type": action.action_type})
        self._commit()
        return True

    def action_by_key(self, key: str) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT * FROM actions WHERE idempotency_key=?", (key,)).fetchone()
        return None if row is None else dict(row)

    def add_event(self, event: MajorEvent) -> None:
        self._conn.execute(
            "INSERT INTO events(id, created_at, severity, title, body, requires_decision, screenshot_path) VALUES(?,?,?,?,?,?,?)",
            (event.id, event.created_at, event.severity.value, event.title, event.body, int(event.requires_decision), event.screenshot_path),
        )
        self.audit("event", "major event recorded", {"id": event.id, "severity": event.severity.value})
        self._commit()

    def recent_events(self, limit: int = 10) -> list[dict[str, Any]]:
        rows = self._conn.execute("SELECT * FROM events ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]

    def audit(self, category: str, message: str, details: dict[str, Any] | None = None) -> None:
        self._conn.execute(
            "INSERT INTO audit_log(created_at, category, message, details_json) VALUES(?,?,?,?)",
            (utc_now(), category, message, json.dumps(details or {}, ensure_ascii=False)),
        )
        self._commit()

    @staticmethod
    def _local_day_bounds_utc(tz_name: str = "Asia/Shanghai") -> tuple[str, str]:
        local_now = datetime.now(ZoneInfo(tz_name))
        start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        return start.astimezone(timezone.utc).isoformat(), end.astimezone(timezone.utc).isoformat()

    def today_action_count(self, tz_name: str = "Asia/Shanghai") -> int:
        start, end = self._local_day_bounds_utc(tz_name)
        return int(self._conn.execute("SELECT COUNT(*) FROM actions WHERE created_at >= ? AND created_at < ?", (start, end)).fetchone()[0])

    def today_actions(self, tz_name: str = "Asia/Shanghai", limit: int = 20) -> list[dict[str, Any]]:
        start, end = self._local_day_bounds_utc(tz_name)
        rows = self._conn.execute(
            "SELECT * FROM actions WHERE created_at >= ? AND created_at < ? ORDER BY created_at DESC LIMIT ?",
            (start, end, limit),
        ).fetchall()
        return [
            {**dict(row), "payload": json.loads(row["payload_json"]), "result": json.loads(row["result_json"]) if row["result_json"] else None}
            for row in rows
        ]

    def recent_observations(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self._conn.execute("SELECT * FROM observations ORDER BY observed_at DESC, rowid DESC LIMIT ?", (limit,)).fetchall()
        return [{**dict(row), "data": json.loads(row["data_json"])} for row in rows]

    def today_token_usage(self, tz_name: str = "Asia/Shanghai") -> dict[str, int]:
        start, end = self._local_day_bounds_utc(tz_name)
        row = self._conn.execute(
            "SELECT COALESCE(SUM(prompt_tokens),0) AS prompt_tokens, "
            "COALESCE(SUM(completion_tokens),0) AS completion_tokens, "
            "COALESCE(SUM(total_tokens),0) AS total_tokens FROM token_usage WHERE recorded_at >= ? AND recorded_at < ?",
            (start, end),
        ).fetchone()
        return {key: int(row[key]) for key in ("prompt_tokens", "completion_tokens", "total_tokens")}
