from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class RiskLevel(StrEnum):
    INFO = "info"
    SAFE = "safe"
    IMPORTANT = "important"
    CRITICAL = "critical"


class ActionStatus(StrEnum):
    PLANNED = "planned"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    SIMULATED = "simulated"
    BLOCKED = "blocked"
    FAILED = "failed"
    UNCERTAIN = "uncertain"


@dataclass(frozen=True)
class RegionSpec:
    name: str
    left: float
    top: float
    right: float
    bottom: float
    focus_instruction: str

    def __post_init__(self) -> None:
        if not 0 <= self.left < self.right <= 1 or not 0 <= self.top < self.bottom <= 1:
            raise ValueError(f"invalid normalized region: {self.name}")

    def crop_box(self, width: int, height: int) -> tuple[int, int, int, int]:
        return (
            round(width * self.left),
            round(height * self.top),
            round(width * self.right),
            round(height * self.bottom),
        )


@dataclass
class Observation:
    data: dict[str, Any]
    source: str = "unknown"
    region: str | None = None
    confidence: float | None = None
    observed_at: str = field(default_factory=utc_now)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Goal:
    title: str
    level: str = "long-term"
    status: str = "active"
    target: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: str = field(default_factory=utc_now)
    completed_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PlannedAction:
    action_type: str
    payload: dict[str, Any]
    risk: RiskLevel = RiskLevel.SAFE
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    idempotency_key: str | None = None

    def key(self) -> str:
        return self.idempotency_key or f"{self.action_type}:{json.dumps(self.payload, sort_keys=True, ensure_ascii=False)}"


@dataclass
class ActionPlan:
    reason: str
    actions: list[PlannedAction]
    plan_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ActionPlan":
        if not isinstance(value, dict) or not isinstance(value.get("actions"), list):
            raise ValueError("action plan must contain an actions list")
        actions: list[PlannedAction] = []
        for raw in value["actions"]:
            if not isinstance(raw, dict) or not isinstance(raw.get("action_type"), str):
                raise ValueError("each action needs action_type")
            payload = raw.get("payload", {})
            if not isinstance(payload, dict):
                raise ValueError("action payload must be an object")
            try:
                risk = RiskLevel(raw.get("risk", RiskLevel.SAFE))
            except ValueError as exc:
                raise ValueError("unknown action risk") from exc
            actions.append(PlannedAction(
                action_type=raw["action_type"],
                payload=payload,
                risk=risk,
                id=str(raw.get("id") or uuid.uuid4()),
                idempotency_key=raw.get("idempotency_key"),
            ))
        return cls(reason=str(value.get("reason", "unspecified")), actions=actions, plan_id=str(value.get("plan_id") or uuid.uuid4()))

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "reason": self.reason,
            "actions": [
                {
                    "id": action.id,
                    "action_type": action.action_type,
                    "payload": action.payload,
                    "risk": action.risk.value,
                    "idempotency_key": action.idempotency_key,
                }
                for action in self.actions
            ],
        }


@dataclass
class MajorEvent:
    title: str
    body: str
    severity: RiskLevel = RiskLevel.IMPORTANT
    requires_decision: bool = False
    screenshot_path: str | None = None
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: str = field(default_factory=utc_now)
