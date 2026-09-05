from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Protocol

from .config import Settings
from .models import ActionPlan, ActionStatus, PlannedAction, RiskLevel
from .storage import SQLiteStore


class ActionExecutor(Protocol):
    def execute(self, action: PlannedAction) -> dict[str, Any]: ...


class ActionVerifier(Protocol):
    def verify(self, action: PlannedAction, execution_result: dict[str, Any]) -> dict[str, Any]: ...


class DryRunExecutor:
    def execute(self, action: PlannedAction) -> dict[str, Any]:
        return {"simulated": True, "action_type": action.action_type, "payload": action.payload}


class LiveActionUnavailable(RuntimeError):
    pass


class DisabledLiveExecutor:
    def execute(self, action: PlannedAction) -> dict[str, Any]:
        raise LiveActionUnavailable(
            "live mouse/keyboard execution is not implemented in this scaffold; use dry-run until a calibrated adapter exists"
        )


@dataclass
class SafetyGate:
    settings: Settings
    store: SQLiteStore

    def check(self, action: PlannedAction) -> tuple[bool, str]:
        if self.store.get_runtime("paused", False):
            return False, "governor is paused"
        if self.store.get_runtime("recovery_required", False):
            return False, "manual recovery acknowledgement is required"
        if action.risk == RiskLevel.CRITICAL and not self.settings.allow_critical_actions:
            return False, "critical action requires explicit enablement"
        if self.settings.execution_mode == "live":
            return False, "live execution adapter is not enabled in this build"
        return True, "allowed in dry-run"


@dataclass
class ActionEngine:
    settings: Settings
    store: SQLiteStore
    executor: ActionExecutor
    verifier: ActionVerifier | None = None

    def __post_init__(self) -> None:
        self.gate = SafetyGate(self.settings, self.store)

    def execute_plan(self, plan: ActionPlan) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for action in plan.actions:
            scoped_key = action.key(plan.plan_id)
            effective_action = replace(action, id=f"{plan.plan_id}:{action.id}")
            previous = self.store.action_by_key(scoped_key)
            if previous is not None:
                results.append({"id": action.id, "status": "skipped_duplicate", "previous": previous["status"]})
                continue
            allowed, reason = self.gate.check(effective_action)
            if not allowed:
                self.store.record_action(effective_action, ActionStatus.BLOCKED, {"reason": reason}, idempotency_key=scoped_key)
                results.append({"id": action.id, "status": ActionStatus.BLOCKED.value, "reason": reason})
                continue
            self.store.record_action(effective_action, ActionStatus.RUNNING, {"reason": reason}, idempotency_key=scoped_key)
            try:
                result = self.executor.execute(effective_action)
            except Exception as exc:  # noqa: BLE001 — turn uncertainty into a safe halt
                self.store.record_action(effective_action, ActionStatus.UNCERTAIN, {"error": str(exc)}, idempotency_key=scoped_key)
                self.store.set_runtime("recovery_required", True)
                results.append({"id": action.id, "status": ActionStatus.UNCERTAIN.value, "error": str(exc)})
                continue
            if self.verifier is not None:
                try:
                    result = {**result, "verification": self.verifier.verify(effective_action, result)}
                except Exception as exc:  # noqa: BLE001 — verification failure is unsafe to ignore
                    self.store.record_action(effective_action, ActionStatus.UNCERTAIN, {"error": str(exc), "phase": "verification"}, idempotency_key=scoped_key)
                    self.store.set_runtime("recovery_required", True)
                    results.append({"id": action.id, "status": ActionStatus.UNCERTAIN.value, "error": str(exc)})
                    continue
            self.store.record_action(effective_action, ActionStatus.SIMULATED, result, idempotency_key=scoped_key)
            results.append({"id": action.id, "status": ActionStatus.SIMULATED.value, "result": result})
        return results
