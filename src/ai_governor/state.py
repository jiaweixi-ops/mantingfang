from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable

from .models import Observation


FIELD_ALIASES = {
    "人口": "population",
    "金钱": "money",
    "资金": "money",
    "粮食": "food",
    "粮食储备": "food",
    "木材": "wood",
    "石材": "stone",
    "劳动力": "labor",
    "幸福度": "happiness",
    "游戏日期": "game_time",
    "日期": "game_time",
    "grain": "food",
    "workers": "labor",
}

_IGNORED_KEYS = {"confidence", "crop_box", "errors", "values"}


@dataclass(frozen=True)
class StateValue:
    value: Any
    source: str
    region: str | None
    observed_at: str
    confidence: float | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CanonicalGameState:
    """Merged state with field-level provenance and explicit conflicts."""

    values: dict[str, Any]
    provenance: dict[str, StateValue]
    conflicts: list[dict[str, Any]]
    observed_at: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "values": dict(self.values),
            "provenance": {name: value.to_dict() for name, value in self.provenance.items()},
            "conflicts": list(self.conflicts),
            "observed_at": self.observed_at,
        }


@dataclass(frozen=True)
class StateAggregator:
    """Merge read-only memory and vision facts without hiding disagreements."""

    source_priority: tuple[tuple[str, int], ...] = (
        ("readonly-memory", 100),
        ("deepseek-vision", 50),
    )

    def aggregate(self, observations: Iterable[Observation]) -> CanonicalGameState:
        selected: dict[str, StateValue] = {}
        conflicts: list[dict[str, Any]] = []
        latest: str | None = None
        for observation in observations:
            latest = max(latest or observation.observed_at, observation.observed_at)
            for raw_name, value in self._fields(observation):
                if value is None:
                    continue
                name = self._canonical_name(raw_name)
                candidate = StateValue(
                    value=value,
                    source=observation.source,
                    region=observation.region,
                    observed_at=observation.observed_at,
                    confidence=observation.confidence,
                )
                current = selected.get(name)
                if current is None:
                    selected[name] = candidate
                    continue
                if current.value != candidate.value:
                    conflicts.append({
                        "field": name,
                        "kept": current.to_dict(),
                        "discarded": candidate.to_dict(),
                    })
                if self._rank(candidate) > self._rank(current):
                    selected[name] = candidate
        return CanonicalGameState(
            values={name: item.value for name, item in selected.items()},
            provenance=selected,
            conflicts=conflicts,
            observed_at=latest,
        )

    def _fields(self, observation: Observation) -> Iterable[tuple[str, Any]]:
        data = observation.data
        nested = data.get("values")
        if isinstance(nested, dict):
            yield from nested.items()
        for name, value in data.items():
            if name not in _IGNORED_KEYS:
                yield name, value

    def _canonical_name(self, name: str) -> str:
        normalized = str(name).strip()
        return FIELD_ALIASES.get(normalized, normalized.casefold())

    def _rank(self, value: StateValue) -> tuple[int, str]:
        priority = dict(self.source_priority).get(value.source, 10)
        return priority, value.observed_at
