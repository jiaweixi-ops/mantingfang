from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .models import MajorEvent, Observation, RiskLevel
from .storage import SQLiteStore


@dataclass
class MajorEventDetector:
    """Turn structured Vision facts into deduplicated major events."""

    store: SQLiteStore

    def detect(self, observations: Iterable[Observation]) -> list[MajorEvent]:
        events: list[MajorEvent] = []
        known = {(item["title"], item["body"]) for item in self.store.recent_events(100)}
        for observation in observations:
            for raw in self._candidates(observation):
                event = self._event(raw)
                if event is None or (event.title, event.body) in known:
                    continue
                known.add((event.title, event.body))
                events.append(event)
        return events

    @staticmethod
    def _candidates(observation: Observation) -> list[dict[str, Any]]:
        data = observation.data
        candidates: list[dict[str, Any]] = []
        for key in ("major_events", "events"):
            raw = data.get(key)
            if isinstance(raw, list):
                candidates.extend(item for item in raw if isinstance(item, dict))
        for key in ("major_event", "event"):
            raw = data.get(key)
            if isinstance(raw, dict):
                candidates.append(raw)
        if isinstance(data.get("event_title"), str) and isinstance(data.get("event_body"), str):
            candidates.append(data)
        return candidates

    @staticmethod
    def _event(raw: dict[str, Any]) -> MajorEvent | None:
        title = raw.get("title") or raw.get("event_title")
        body = raw.get("body") or raw.get("event_body") or raw.get("description")
        if not isinstance(title, str) or not title.strip() or not isinstance(body, str) or not body.strip():
            return None
        try:
            severity = RiskLevel(str(raw.get("severity", RiskLevel.IMPORTANT)).lower())
        except ValueError:
            severity = RiskLevel.IMPORTANT
        requires_decision = bool(raw.get("requires_decision", False)) or severity == RiskLevel.CRITICAL
        if severity == RiskLevel.INFO and not requires_decision:
            return None
        return MajorEvent(
            title=title.strip(),
            body=body.strip(),
            severity=severity,
            requires_decision=requires_decision,
        )
