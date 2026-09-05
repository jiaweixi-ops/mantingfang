from __future__ import annotations

import time
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from .actions import ActionEngine
from .capture import CaptureBlackFrameError, ClientAreaCapture, Win32ClientCaptureBackend
from .config import Settings
from .deepseek import DeepSeekClient, DeepSeekConfigurationError
from .models import ActionPlan, PlannedAction
from .perception import PerceptionEngine, RegionCatalog
from .storage import SQLiteStore
from .window import ForegroundTimeout, SteamWindowAdapter, Win32WindowBackend, WindowError


class E2EConfigurationError(RuntimeError):
    pass


class E2EPreflightError(RuntimeError):
    pass


def _preflight_observation_summary(data: dict[str, Any]) -> dict[str, Any]:
    """Persist only bounded, non-secret calibration facts."""
    summary: dict[str, Any] = {}
    for key in ("build_menu_open", "dialog_open", "current_screen", "confidence"):
        if key in data:
            summary[key] = data[key]
    elements = data.get("ui_elements")
    if isinstance(elements, list):
        summary["ui_elements"] = [
            {
                "id": item.get("id"),
                "label": item.get("label"),
                "bbox": item.get("bbox"),
                "global_bbox": item.get("global_bbox"),
            }
            for item in elements
            if isinstance(item, dict)
        ]
    return summary


def run_read_only_preflight(
    settings: Settings,
    store: SQLiteStore,
    *,
    wait_for_game_foreground: bool = False,
    timeout_seconds: float = 30.0,
    stable_seconds: float = 3.0,
    poll_seconds: float = 0.5,
    output_dir: Path = Path("data/e2e"),
) -> dict[str, Any]:
    """Wait for the real game window and perform capture/Vision checks only."""
    if not settings.deepseek_api_key:
        raise DeepSeekConfigurationError("DEEPSEEK_API_KEY is not configured")
    if not settings.deepseek_vision_model:
        raise DeepSeekConfigurationError("DEEPSEEK_VISION_MODEL is not configured")

    output_dir.mkdir(parents=True, exist_ok=True)
    window = SteamWindowAdapter(settings.game_window_title, Win32WindowBackend())
    try:
        if wait_for_game_foreground:
            info = window.wait_for_foreground(
                timeout_seconds=timeout_seconds,
                stable_seconds=stable_seconds,
                poll_seconds=poll_seconds,
            )
        else:
            info = window.locate()
            window.require_foreground(info)
    except ForegroundTimeout as exc:
        raise E2EPreflightError("FOREGROUND_TIMEOUT") from exc
    except WindowError as exc:
        raise E2EPreflightError(f"FOREGROUND_ERROR: {exc}") from exc

    capture = ClientAreaCapture(window, Win32ClientCaptureBackend())
    frame = capture.capture()
    (output_dir / "preflight.png").write_bytes(frame.png)
    diagnostic = frame.diagnostic.to_dict() if frame.diagnostic else {
        "hwnd": info.hwnd,
        "client_width": info.client_width,
        "client_height": info.client_height,
        "capture_backend": type(capture.backend).__name__,
        "raster_mode": "unknown",
        "near_black_frame": False,
        "status": "UNKNOWN",
    }
    if diagnostic["near_black_frame"]:
        raise E2EPreflightError("CAPTURE_BLACK_FRAME")

    client = DeepSeekClient(
        settings.deepseek_api_base,
        settings.deepseek_api_key,
        settings.deepseek_vision_model,
        usage_callback=store.record_token_usage,
    )
    perception = PerceptionEngine(client, RegionCatalog(), model=settings.deepseek_vision_model)
    observations: dict[str, dict[str, Any]] = {}
    for region_name in ("build_menu", "dialog"):
        try:
            observation = perception.observe_rgba(
                frame.rgba,
                frame.width,
                frame.height,
                region_name,
                context="E2E 只读预检；不执行任何游戏操作",
            )
        except Exception as exc:
            raise E2EPreflightError(f"VISION_ERROR: {type(exc).__name__}: {exc}") from exc
        observations[region_name] = _preflight_observation_summary(observation.data)

    report = {
        "status": "PASS",
        "wait_for_game_foreground": wait_for_game_foreground,
        "foreground_stable_seconds": stable_seconds if wait_for_game_foreground else None,
        "window": {
            "hwnd": info.hwnd,
            "title": info.title,
            "client_width": info.client_width,
            "client_height": info.client_height,
            "minimized": info.minimized,
        },
        "capture": diagnostic,
        "vision": observations,
        "live_input": {
            "arm_live_called": False,
            "input_sent": False,
        },
    }
    (output_dir / "preflight_vision.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


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
