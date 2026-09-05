from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from .capture import ClientAreaCapture
from .models import PlannedAction
from .window import SteamWindowAdapter


class VerificationError(RuntimeError):
    pass


class ActionVerifier(Protocol):
    def verify(self, action: PlannedAction, execution_result: dict[str, Any]) -> dict[str, Any]: ...


@dataclass
class ScreenshotVerifier:
    window: SteamWindowAdapter
    capture: ClientAreaCapture
    semantic: bool = False

    def verify(self, action: PlannedAction, execution_result: dict[str, Any]) -> dict[str, Any]:
        info = self.window.locate()
        if info.minimized:
            raise VerificationError("game window is minimized after action")
        frame = self.capture.capture()
        return {
            "verified": True,
            "method": "client-screenshot",
            "action_type": action.action_type,
            "width": frame.width,
            "height": frame.height,
            "png_sha256": hashlib.sha256(frame.png).hexdigest(),
        }


@dataclass
class SemanticStateVerifier:
    """Verify an action through an observable state predicate, not screenshot existence."""

    observe_state: Callable[[], dict[str, Any]]
    timeout_seconds: float = 5.0
    poll_interval_seconds: float = 0.1
    semantic: bool = True

    def verify(self, action: PlannedAction, execution_result: dict[str, Any]) -> dict[str, Any]:
        expected = action.payload.get("expected_state")
        changed_fields = action.payload.get("changed_fields")
        before = execution_result.get("before_state")
        if not isinstance(expected, dict) and not isinstance(changed_fields, list):
            raise VerificationError("semantic verification requires expected_state or changed_fields")
        deadline = time.monotonic() + max(0.0, self.timeout_seconds)
        last = self.observe_state()
        while True:
            if self._matches(last, before, expected, changed_fields):
                return {"verified": True, "method": "semantic-state", "state": last}
            if time.monotonic() >= deadline:
                raise VerificationError(f"action state predicate not satisfied: {action.action_type}")
            time.sleep(max(0.0, self.poll_interval_seconds))
            last = self.observe_state()

    @staticmethod
    def _matches(after: dict[str, Any], before: Any, expected: Any, changed_fields: Any) -> bool:
        if isinstance(expected, dict) and any(after.get(key) != value for key, value in expected.items()):
            return False
        if isinstance(changed_fields, list):
            if not isinstance(before, dict):
                return False
            if not any(before.get(key) != after.get(key) for key in changed_fields if isinstance(key, str)):
                return False
        return True
