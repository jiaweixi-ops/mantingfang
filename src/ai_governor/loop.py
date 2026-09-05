from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass
from typing import Any, Protocol

from .models import Observation
from .storage import SQLiteStore
from .watchdog import Watchdog


class ObservationSource(Protocol):
    def observe(self) -> Observation | list[Observation]: ...


class CycleRunner(Protocol):
    def run_cycle(self, observation: Observation) -> dict[str, Any]: ...


@dataclass(frozen=True)
class LoopCycle:
    number: int
    status: str
    detail: dict[str, Any]


@dataclass
class GovernorLoop:
    source: ObservationSource
    runner: CycleRunner
    store: SQLiteStore
    watchdog: Watchdog
    interval_seconds: float = 10.0
    max_observation_errors: int = 3

    def __post_init__(self) -> None:
        if self.interval_seconds < 0:
            raise ValueError("interval_seconds must be non-negative")
        if self.max_observation_errors < 1:
            raise ValueError("max_observation_errors must be positive")
        self._last_fingerprint: str | None = None
        self._observation_errors = 0

    @staticmethod
    def fingerprint(observations: Observation | list[Observation]) -> str:
        items = observations if isinstance(observations, list) else [observations]
        payload = [{
            "source": observation.source,
            "region": observation.region,
            "data": observation.data,
        } for observation in items]
        return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()

    def run_once(self, number: int) -> LoopCycle:
        self.watchdog.heartbeat()
        try:
            raw_observations = self.source.observe()
            observations = raw_observations if isinstance(raw_observations, list) else [raw_observations]
            if not observations or any(not isinstance(item, Observation) for item in observations):
                raise TypeError("observation source must return Observation or non-empty list[Observation]")
        except Exception as exc:  # noqa: BLE001 — repeated sensor failure must stop safely
            self._observation_errors += 1
            self.store.audit("loop", "observation failed", {"cycle": number, "error": str(exc), "count": self._observation_errors})
            if self._observation_errors >= self.max_observation_errors:
                self.watchdog.require_recovery("observation source failed repeatedly")
                return LoopCycle(number, "needs_recovery", {"error": str(exc), "count": self._observation_errors})
            return LoopCycle(number, "observation_error", {"error": str(exc), "count": self._observation_errors})

        self._observation_errors = 0
        fingerprint = self.fingerprint(observations)
        if fingerprint == self._last_fingerprint:
            return LoopCycle(number, "unchanged", {"fingerprint": fingerprint})
        self._last_fingerprint = fingerprint
        run_many = getattr(self.runner, "run_observations", None)
        result = run_many(observations) if callable(run_many) else self.runner.run_cycle(observations[0])
        return LoopCycle(number, "changed", result)

    def run(self, *, max_cycles: int | None = None, stop_event: threading.Event | None = None) -> list[LoopCycle]:
        if max_cycles is not None and max_cycles < 1:
            raise ValueError("max_cycles must be positive when provided")
        stop = stop_event or threading.Event()
        cycles: list[LoopCycle] = []
        number = 0
        while not stop.is_set() and (max_cycles is None or number < max_cycles):
            number += 1
            cycle = self.run_once(number)
            cycles.append(cycle)
            if cycle.status == "needs_recovery" or self.store.get_runtime("recovery_required", False):
                break
            if number < (max_cycles or number + 1) and stop.wait(self.interval_seconds):
                break
        return cycles


@dataclass
class CompositeObservationSource:
    sources: tuple[ObservationSource, ...]

    def observe(self) -> list[Observation]:
        observations: list[Observation] = []
        for source in self.sources:
            result = source.observe()
            observations.extend(result if isinstance(result, list) else [result])
        if not observations:
            raise RuntimeError("composite observation source has no observations")
        return observations
