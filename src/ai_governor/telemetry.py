from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

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
        return payload

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
