from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Protocol

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
