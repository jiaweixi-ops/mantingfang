from __future__ import annotations

import json
import math
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from collections.abc import Callable

from .models import Observation


class RuntimeTelemetryError(RuntimeError):
    """Base class for unavailable or invalid read-only bridge telemetry."""


class RuntimeTelemetryUnavailable(RuntimeTelemetryError):
    pass


class RuntimeTelemetrySchemaError(RuntimeTelemetryError):
    pass


@dataclass(frozen=True)
class RuntimeTelemetryClient:
    base_url: str = "http://127.0.0.1:18765"
    timeout_seconds: float = 1.5
    expected_pid: int | None = None
    expected_game_version: str | None = None
    max_age_seconds: float = 2.0
    clock: Callable[[], float] | None = None

    def _get_json(self, path: str) -> dict[str, Any]:
        request = urllib.request.Request(f"{self.base_url.rstrip('/')}{path}", method="GET")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise RuntimeTelemetryUnavailable(f"runtime telemetry unavailable: {type(exc).__name__}") from exc
        if not isinstance(payload, dict):
            raise RuntimeTelemetrySchemaError("runtime telemetry response must be an object")
        return payload

    def health(self) -> dict[str, Any]:
        return self._get_json("/health")

    def read(self) -> dict[str, Any]:
        payload = self._get_json("/state")
        if payload.get("source") != "runtime_bridge":
            raise RuntimeTelemetrySchemaError("unexpected runtime telemetry source")
        if payload.get("status") != "OK":
            raise RuntimeTelemetrySchemaError(f"runtime telemetry status={payload.get('status', 'MISSING')}")
        if not isinstance(payload.get("game_pid"), int) or payload["game_pid"] <= 0:
            raise RuntimeTelemetrySchemaError("runtime telemetry missing valid game_pid")
        if self.expected_pid is not None and payload["game_pid"] != self.expected_pid:
            raise RuntimeTelemetrySchemaError(
                f"RUNTIME_PROCESS_CHANGED: expected={self.expected_pid}, actual={payload['game_pid']}"
            )
        game_version = payload.get("game_version")
        if not isinstance(game_version, str) or not game_version.strip():
            raise RuntimeTelemetrySchemaError("runtime telemetry missing game_version")
        if self.expected_game_version and game_version != self.expected_game_version:
            raise RuntimeTelemetrySchemaError(
                f"RUNTIME_VERSION_MISMATCH: expected={self.expected_game_version}, actual={game_version}"
            )
        observed_at = payload.get("observed_at")
        if not isinstance(observed_at, str) or not observed_at.strip():
            raise RuntimeTelemetrySchemaError("runtime telemetry missing observed_at")
        try:
            timestamp = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise RuntimeTelemetrySchemaError("runtime telemetry observed_at is invalid") from exc
        if timestamp.tzinfo is None:
            raise RuntimeTelemetrySchemaError("runtime telemetry observed_at must include timezone")
        now = self.clock() if self.clock is not None else datetime.now(timezone.utc).timestamp()
        age = now - timestamp.timestamp()
        if age < -self.max_age_seconds or age > self.max_age_seconds:
            raise RuntimeTelemetrySchemaError(f"RUNTIME_STALE: snapshot_age_seconds={age:.3f}")
        self._validate_state_schema(payload)
        return payload

    @staticmethod
    def _validate_state_schema(payload: dict[str, Any]) -> None:
        required = {
            "city_name",
            "year",
            "month",
            "gold",
            "population",
            "resources",
            "buildings_count",
            "sites_count",
            "build_menu_open",
        }
        missing = sorted(key for key in required if key not in payload)
        if missing:
            raise RuntimeTelemetrySchemaError(f"runtime telemetry missing fields: {', '.join(missing)}")

        city_name = payload["city_name"]
        if not isinstance(city_name, str) or not city_name.strip():
            raise RuntimeTelemetrySchemaError("runtime telemetry city_name must be a non-empty string")
        for key in ("year", "month", "population", "buildings_count", "sites_count"):
            value = payload[key]
            if type(value) is not int or value < 0:
                raise RuntimeTelemetrySchemaError(f"runtime telemetry {key} must be a non-negative integer")
        if not RuntimeTelemetryClient._is_non_negative_number(payload["gold"]):
            raise RuntimeTelemetrySchemaError("runtime telemetry gold must be a non-negative number")
        if type(payload["build_menu_open"]) is not bool:
            raise RuntimeTelemetrySchemaError("runtime telemetry build_menu_open must be bool")
        resources = payload["resources"]
        if not isinstance(resources, dict):
            raise RuntimeTelemetrySchemaError("runtime telemetry resources must be an object")
        required_resources = {"rice", "vegetable", "wood", "stone"}
        missing_resources = sorted(name for name in required_resources if name not in resources)
        if missing_resources:
            raise RuntimeTelemetrySchemaError(
                f"runtime telemetry resources missing fields: {', '.join(missing_resources)}"
            )
        for name in required_resources:
            if not RuntimeTelemetryClient._is_non_negative_number(resources[name]):
                raise RuntimeTelemetrySchemaError(
                    f"runtime telemetry resources.{name} must be a non-negative number"
                )

    @staticmethod
    def _is_non_negative_number(value: Any) -> bool:
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
            and value >= 0
        )

    def observe(self) -> Observation:
        payload = self.read()
        return Observation(
            data=payload,
            source="runtime-telemetry",
            region="runtime",
            confidence=1.0,
        )


@dataclass(frozen=True)
class RuntimeTelemetryObservationSource:
    client: RuntimeTelemetryClient

    def observe(self) -> Observation:
        return self.client.observe()
