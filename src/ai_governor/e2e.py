from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from .actions import ActionEngine
from .config import Settings
from .models import ActionPlan, PlannedAction
from .storage import SQLiteStore


class E2EConfigurationError(RuntimeError):
    pass


@dataclass
class BuildMenuE2EHarness:
    settings: Settings
    store: SQLiteStore
    actions: ActionEngine
    open_element: str = "build_menu_button"
    close_element: str = "close_build_menu"

    def run(self, *, attempts: int = 100, confirm_live: bool = False) -> dict[str, Any]:
        if not confirm_live:
            raise E2EConfigurationError("real E2E requires --confirm-live-e2e")
        if attempts < 1:
            raise E2EConfigurationError("E2E attempts must be positive")
        if self.settings.execution_mode != "live" or not self.settings.allow_live_input:
            raise E2EConfigurationError("real E2E requires live mode and GOVERNOR_ALLOW_LIVE_INPUT=true")
        if not self.store.get_runtime("live_armed", False):
            raise E2EConfigurationError("real E2E requires explicit live arming")
        if self.actions.verifier is None or not getattr(self.actions.verifier, "semantic", False):
            raise E2EConfigurationError("real E2E requires semantic verification")
        if not self.open_element or not self.close_element:
            raise E2EConfigurationError("open and close UI element ids are required")

        run_id = uuid4().hex
        started = time.perf_counter()
        metrics = {
            "run_id": run_id,
            "requested_attempts": attempts,
            "completed_attempts": 0,
            "open_succeeded": 0,
            "close_succeeded": 0,
            "blocked": 0,
            "uncertain": 0,
            "wrong_window_or_foreground": 0,
            "recovery_required": False,
            "passed": False,
        }
        for index in range(1, attempts + 1):
            for phase, skill, element, expected in (
                ("open", "OPEN_BUILD_MENU", self.open_element, True),
                ("close", "CLOSE_BUILD_MENU", self.close_element, False),
            ):
                plan = ActionPlan(
                    reason=f"E2E-001 build menu {phase} cycle {index}",
                    actions=[PlannedAction(
                        skill,
                        {
                            "target_region": "build_menu",
                            "target_element": element,
                            "expected_state": {"build_menu_open": expected},
                            "e2e_cycle": index,
                        },
                    )],
                )
                result = self.actions.execute_plan(plan)[0]
                status = result.get("status")
                if status == "succeeded":
                    metrics[f"{phase}_succeeded"] += 1
                elif status == "blocked":
                    metrics["blocked"] += 1
                else:
                    metrics["uncertain"] += 1
                    error = str(result.get("error", ""))
                    if "foreground" in error or "window" in error:
                        metrics["wrong_window_or_foreground"] += 1
                if status != "succeeded":
                    metrics["recovery_required"] = bool(self.store.get_runtime("recovery_required", False))
                    metrics["elapsed_seconds"] = round(time.perf_counter() - started, 3)
                    return metrics
            metrics["completed_attempts"] += 1
        metrics["passed"] = metrics["completed_attempts"] == attempts
        metrics["recovery_required"] = bool(self.store.get_runtime("recovery_required", False))
        metrics["elapsed_seconds"] = round(time.perf_counter() - started, 3)
        return metrics
