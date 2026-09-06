"""One-click-only real-game Build Menu category navigation.

The implementation deliberately contains no Qwen client and no runtime or
debugger access.  It combines a current WGC frame, local deterministic menu
geometry, the pure category planner, and the existing guarded Win32 input
adapter.  Every failure is terminal for the invocation; there is no retry.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from .build_category_navigator import CategoryNavigationError, plan_build_category_click
from .build_menu import BuildMenuSnapshot, BuildMenuState, FrameGeometry
from .build_menu_observer import BuildMenuCalibrationError, build_local_menu_snapshot
from .capture import CaptureError, ClientAreaCapture, WindowsGraphicsCaptureBackend
from .config import Settings
from .input import InputCommand, InputError, WindowsSendInputAdapter, Win32SendInputBackend
from .perception import RegionCatalog
from .storage import SQLiteStore
from .window import ForegroundTimeout, SteamWindowAdapter, Win32WindowBackend, WindowError, WindowNotFound


class BuildCategoryE2EError(RuntimeError):
    """Raised for a precondition failure before a category input is sent."""


def _locate_window(settings: Settings, backend: Win32WindowBackend, title: str | None) -> SteamWindowAdapter:
    selected = title or settings.game_window_title
    window = SteamWindowAdapter(selected, backend)
    try:
        window.locate()
    except WindowNotFound:
        if title or selected == "Song":
            raise
        window = SteamWindowAdapter("Song", backend)
        window.locate()
    return window


def _require_live_arming(settings: Settings, store: SQLiteStore) -> None:
    if settings.execution_mode != "live" or not settings.allow_live_input:
        raise BuildCategoryE2EError(
            "V2.4C requires GOVERNOR_EXECUTION_MODE=live and GOVERNOR_ALLOW_LIVE_INPUT=true"
        )
    if not store.get_runtime("live_armed", False):
        raise BuildCategoryE2EError("V2.4C requires explicit live arming")


def _frame_matches_window(geometry: FrameGeometry, window: SteamWindowAdapter, info: Any) -> tuple[bool, dict[str, Any]]:
    current = window.geometry_snapshot(info).to_dict()
    matches = (
        geometry.hwnd == current["hwnd"]
        and geometry.pid == current["pid"]
        and geometry.client_width == current["client_width"]
        and geometry.client_height == current["client_height"]
        and geometry.client_origin == (current["screen_left"], current["screen_top"])
        and geometry.dpi == current["dpi"]
    )
    return matches, current


def _capture_snapshot(
    *,
    phase: str,
    capture: ClientAreaCapture,
    backend: Win32WindowBackend,
    catalog: RegionCatalog,
) -> tuple[str, Any, BuildMenuSnapshot]:
    frame = capture.capture()
    snapshot = build_local_menu_snapshot(
        phase=phase,
        frame=frame,
        capture=capture,
        backend=backend,
        catalog=catalog,
    )
    return uuid4().hex, frame, snapshot


def _controls_fingerprint(frame: Any, catalog: RegionCatalog) -> str:
    """Hash only the Build Menu controls region as post-click evidence."""
    left, top, right, bottom = catalog.get("build_controls").crop_box(frame.width, frame.height)
    rows = bytearray()
    for y in range(top, bottom):
        start = (y * frame.width + left) * 4
        end = (y * frame.width + right) * 4
        rows.extend(frame.rgba[start:end])
    return hashlib.sha256(rows).hexdigest()


def _snapshot_summary(frame_id: str, snapshot: BuildMenuSnapshot, frame: Any, catalog: RegionCatalog) -> dict[str, Any]:
    return {
        "frame_id": frame_id,
        "state": snapshot.state.value,
        "geometry": snapshot.geometry.to_dict() if snapshot.geometry else None,
        "close_control": snapshot.close_control,
        "categories_found": len(snapshot.categories),
        "options_found": len(snapshot.options),
        "controls_fingerprint": _controls_fingerprint(frame, catalog),
        "capture": frame.diagnostic.to_dict() if frame.diagnostic else None,
    }


def run_build_category_dry_run(
    settings: Settings,
    *,
    output_dir: Path,
    window_title: str | None = None,
) -> dict[str, Any]:
    """Produce a non-actionable V2.4C plan from one fresh root frame."""
    output_dir.mkdir(parents=True, exist_ok=True)
    backend = Win32WindowBackend()
    window = _locate_window(settings, backend, window_title)
    capture = ClientAreaCapture(window, WindowsGraphicsCaptureBackend(), reject_near_black=True)
    catalog = RegionCatalog()
    frame_id, frame, snapshot = _capture_snapshot(
        phase="root", capture=capture, backend=backend, catalog=catalog
    )
    if snapshot.state is not BuildMenuState.ROOT_OPEN:
        raise BuildCategoryE2EError(f"dry run requires ROOT_OPEN, got {snapshot.state.value}")
    info = window.locate()
    geometry_matches, current_geometry = _frame_matches_window(snapshot.geometry, window, info) if snapshot.geometry else (False, {})
    if not geometry_matches:
        raise BuildCategoryE2EError("TARGET_STALE: game geometry changed during dry-run planning")
    plan = plan_build_category_click(snapshot, frame_id=frame_id)
    result = {
        "phase": "V2.4C",
        "mode": "dry_run",
        "precondition": _snapshot_summary(frame_id, snapshot, frame, catalog),
        "plan": plan.to_dict(),
        "window_geometry": current_geometry,
        "qwen_calls": 0,
        "sendinput_calls": 0,
        "keyboard_inputs": 0,
        "map_clicks": 0,
        "building_option_clicks": 0,
        "retries": 0,
        "result": "PASS",
    }
    (output_dir / "dry_run.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def run_live_build_category_once(
    settings: Settings,
    store: SQLiteStore,
    *,
    output_dir: Path,
    window_title: str | None = None,
    wait_for_game_foreground: bool = False,
    foreground_timeout_seconds: float = 30.0,
    settle_seconds: float = 0.6,
) -> dict[str, Any]:
    """Perform exactly one current-frame category click, then stop and verify."""
    _require_live_arming(settings, store)
    if foreground_timeout_seconds <= 0 or settle_seconds < 0:
        raise BuildCategoryE2EError("V2.4C timing values are invalid")
    output_dir.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "phase": "V2.4C",
        "max_clicks": 1,
        "clicks": 0,
        "qwen_calls": 0,
        "map_clicks": 0,
        "building_option_clicks": 0,
        "keyboard_inputs": 0,
        "retries": 0,
        "save_writes": 0,
        "memory_writes": 0,
        "runtime_telemetry": False,
        "mono_debugger": False,
        "result": "FAIL",
    }
    try:
        backend = Win32WindowBackend()
        window = _locate_window(settings, backend, window_title)
        if wait_for_game_foreground:
            info = window.wait_for_foreground(
                timeout_seconds=foreground_timeout_seconds,
                stable_seconds=3.0,
                poll_seconds=0.5,
            )
        else:
            info = window.locate()
            window.require_foreground(info)
        expected_pid = backend.window_process_id(info.hwnd)
        if expected_pid is None:
            raise BuildCategoryE2EError("current Song HWND has no readable PID")
        if info.minimized:
            raise BuildCategoryE2EError("Song is minimized")
        capture = ClientAreaCapture(window, WindowsGraphicsCaptureBackend(), reject_near_black=True)
        catalog = RegionCatalog()
        before_id, before_frame, before = _capture_snapshot(
            phase="root", capture=capture, backend=backend, catalog=catalog
        )
        if before.state is not BuildMenuState.ROOT_OPEN:
            raise BuildCategoryE2EError(f"pre_state must be ROOT_OPEN, got {before.state.value}")
        if before.geometry is None:
            raise BuildCategoryE2EError("ROOT_OPEN snapshot has no geometry")
        if before.geometry.hwnd != info.hwnd or before.geometry.pid != expected_pid:
            raise BuildCategoryE2EError("TARGET_STALE: current root frame identity does not match Song")
        geometry_matches, input_geometry = _frame_matches_window(before.geometry, window, info)
        if not geometry_matches:
            raise BuildCategoryE2EError("TARGET_STALE: game geometry changed after ROOT_OPEN capture")
        plan = plan_build_category_click(before, frame_id=before_id)
        report["pre_state"] = before.state.value
        report["precondition"] = _snapshot_summary(before_id, before, before_frame, catalog)
        report["target"] = plan.to_dict()
        report["target_role"] = "BUILD_CATEGORY_TAB"
        report["window"] = {"hwnd": info.hwnd, "pid": expected_pid, "geometry": input_geometry}

        adapter = WindowsSendInputAdapter(
            window,
            Win32SendInputBackend(),
            enabled=True,
            allow_clicks=True,
            allow_keyboard=False,
            expected_pid=expected_pid,
            auto_foreground=False,
        )
        with adapter.action_transaction():
            # Re-check exact foreground, PID, and geometry inside the one
            # input transaction.  The adapter repeats these checks immediately
            # before down and up as well.
            transaction_info = window.require_foreground(window.locate())
            transaction_matches, transaction_geometry = _frame_matches_window(before.geometry, window, transaction_info)
            if not transaction_matches:
                raise BuildCategoryE2EError("TARGET_STALE: geometry changed before category input")
            if backend.window_process_id(transaction_info.hwnd) != expected_pid:
                raise BuildCategoryE2EError("TARGET_STALE: Song PID changed before category input")
            input_result = adapter.execute(InputCommand(
                "click",
                plan.click_point[0],
                plan.click_point[1],
                geometry_snapshot=transaction_geometry,
            ))
        report["clicks"] = 1
        report["input"] = {"backend": "Win32SendInputBackend", "result": input_result}

        if settle_seconds:
            time.sleep(settle_seconds)
        after_info = window.locate()
        if after_info.hwnd != info.hwnd or backend.window_process_id(after_info.hwnd) != expected_pid:
            raise BuildCategoryE2EError("postcondition window identity changed")
        after_id, after_frame, after = _capture_snapshot(
            phase="category", capture=capture, backend=backend, catalog=catalog
        )
        if after.geometry is None:
            raise BuildCategoryE2EError("CATEGORY_OPEN postcondition has no geometry")
        after_matches, _after_input_geometry = _frame_matches_window(after.geometry, window, after_info)
        if not after_matches:
            raise BuildCategoryE2EError("TARGET_STALE: game geometry changed before postcondition capture")
        post = _snapshot_summary(after_id, after, after_frame, catalog)
        post["controls_changed"] = post["controls_fingerprint"] != report["precondition"]["controls_fingerprint"]
        report["postcondition"] = post
        report["post_state"] = after.state.value
        report["options_found"] = len(after.options)
        report["game_responsive_after"] = bool(backend.is_window(after_info.hwnd) and not after_info.minimized)
        if after.state is BuildMenuState.BUILDING_SELECTED:
            report["failure_class"] = "SAFETY_FAIL_UNEXPECTED_SELECTION"
            report["failure_reason"] = "postcondition entered BUILDING_SELECTED"
        elif after.state is not BuildMenuState.CATEGORY_OPEN:
            report["failure_class"] = "FAIL_UNKNOWN_POSTCONDITION" if after.state is BuildMenuState.UNKNOWN else "FAIL_POSTCONDITION"
            report["failure_reason"] = f"expected CATEGORY_OPEN, got {after.state.value}"
        elif len(after.options) < 1:
            report["failure_class"] = "FAIL_POSTCONDITION"
            report["failure_reason"] = "CATEGORY_OPEN has no local BUILD_OPTION slots"
        elif not post["controls_changed"]:
            report["failure_class"] = "FAIL_POSTCONDITION"
            report["failure_reason"] = "build_controls pixels did not change after the one category click"
        elif not report["game_responsive_after"]:
            report["failure_class"] = "FAIL_POSTCONDITION"
            report["failure_reason"] = "Song is not responsive after category click"
        else:
            report["result"] = "PASS"
    except (BuildCategoryE2EError, CategoryNavigationError, BuildMenuCalibrationError, CaptureError, InputError, WindowError, OSError, ValueError) as exc:
        report["failure_class"] = type(exc).__name__
        report["failure_reason"] = str(exc)
    except Exception as exc:  # noqa: BLE001 - one-click path must always disarm and report.
        report["failure_class"] = type(exc).__name__
        report["failure_reason"] = str(exc)
    finally:
        store.set_runtime("live_armed", False)
        report["arm_live"] = False
        report["input_sent"] = report["clicks"] > 0
        (output_dir / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report
