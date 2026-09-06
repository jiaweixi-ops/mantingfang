"""Guarded V2.4E/F live select-and-cancel roundtrip.

This module is intentionally strict about the handoff from the read-only
calibration phase. A manual click recorded by V2.4E0 is not a safe target
identity. The live phase may proceed only when E0 (or a later explicit
calibration) records a proven slot identity that can be resolved again from a
fresh current frame.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from .build_category_e2e import _frame_matches_window, _locate_window
from .build_menu import BuildMenuSnapshot, BuildMenuState
from .build_menu_observer import BuildMenuCalibrationError, build_local_menu_snapshot
from .build_placement import (
    analyze_placement_transition,
    detect_current_frame_cancel_controls,
    placement_snapshot,
    validate_fresh_cancel_target,
)
from .capture import CaptureError, ClientAreaCapture, WindowsGraphicsCaptureBackend
from .config import Settings
from .input import InputCommand, InputError, InputSafetyMode, WindowsSendInputAdapter, Win32SendInputBackend
from .perception import RegionCatalog
from .storage import SQLiteStore
from .window import WindowError, Win32WindowBackend


MIN_CONFIDENCE = 0.90


class BuildPlacementLiveError(RuntimeError):
    """Raised for a fail-closed V2.4E/F precondition or postcondition."""


@dataclass(frozen=True)
class BuildOptionSelectionPlan:
    frame_id: str
    hwnd: int
    pid: int
    slot_id: str
    bbox: tuple[float, float, float, float]
    global_bbox: tuple[float, float, float, float]
    click_point: tuple[float, float]
    confidence: float
    geometry: dict[str, Any]
    safe_click_box: tuple[float, float, float, float]
    provenance: str

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        for key in ("bbox", "global_bbox", "click_point", "safe_click_box"):
            value[key] = list(value[key])
        return value


def _inside(bbox: tuple[float, float, float, float]) -> bool:
    return 0.0 <= bbox[0] < bbox[2] <= 1.0 and 0.0 <= bbox[1] < bbox[3] <= 1.0


def _safe_center(bbox: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    width, height = bbox[2] - bbox[0], bbox[3] - bbox[1]
    return (
        bbox[0] + width * 0.30,
        bbox[1] + height * 0.30,
        bbox[2] - width * 0.30,
        bbox[3] - height * 0.30,
    )


def _load_proven_slot(evidence_path: Path) -> dict[str, Any] | None:
    """Load only an explicit E0 identity; never infer one from click counts."""
    if not evidence_path.is_file():
        return None
    try:
        report = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(report, Mapping):
        return None
    identity = report.get("proven_safe_slot")
    if not isinstance(identity, Mapping):
        return None
    if identity.get("basis") != "explicit_current_frame_slot_identity":
        return None
    slot_id = identity.get("slot_id")
    ordinal = identity.get("ordinal")
    if not isinstance(slot_id, str) and not (
        isinstance(ordinal, int) and not isinstance(ordinal, bool) and ordinal > 0
    ):
        return None
    return dict(identity)


def plan_build_option_click(
    snapshot: BuildMenuSnapshot,
    *,
    frame_id: str,
    proven_slot: Mapping[str, Any],
) -> BuildOptionSelectionPlan:
    """Resolve a proven slot against the current frame only."""
    if not isinstance(frame_id, str) or not frame_id.strip():
        raise BuildPlacementLiveError("BUILD_OPTION plan requires a current frame_id")
    if snapshot.state is not BuildMenuState.CATEGORY_OPEN:
        raise BuildPlacementLiveError(f"BUILD_OPTION plan requires CATEGORY_OPEN, got {snapshot.state.value}")
    if snapshot.geometry is None:
        raise BuildPlacementLiveError("BUILD_OPTION plan requires current geometry")
    if (snapshot.evidence or {}).get("option_source") != "deterministic_current_frame_option_slot":
        raise BuildPlacementLiveError("BUILD_OPTION plan rejects non-current-frame option evidence")

    slot_id = proven_slot.get("slot_id")
    ordinal = proven_slot.get("ordinal")
    selected = None
    if isinstance(slot_id, str):
        selected = next((item for item in snapshot.options if item.id == slot_id), None)
    elif isinstance(ordinal, int) and not isinstance(ordinal, bool) and ordinal > 0:
        ordered = sorted(
            snapshot.options,
            key=lambda item: ((item.global_bbox or item.bbox)[1], (item.global_bbox or item.bbox)[0]),
        )
        if ordinal <= len(ordered):
            selected = ordered[ordinal - 1]
    if selected is None:
        raise BuildPlacementLiveError("FAIL_PRECONDITION_PROVEN_SLOT_NOT_FOUND_IN_FRESH_FRAME")
    bbox = selected.global_bbox or selected.bbox
    if selected.confidence < MIN_CONFIDENCE or not _inside(bbox):
        raise BuildPlacementLiveError("FAIL_PRECONDITION_PROVEN_SLOT_NOT_ACTIONABLE")
    safe_box = _safe_center(bbox)
    return BuildOptionSelectionPlan(
        frame_id=frame_id,
        hwnd=snapshot.geometry.hwnd,
        pid=snapshot.geometry.pid,
        slot_id=selected.id,
        bbox=selected.bbox,
        global_bbox=bbox,
        click_point=((safe_box[0] + safe_box[2]) / 2.0, (safe_box[1] + safe_box[3]) / 2.0),
        confidence=selected.confidence,
        geometry=snapshot.geometry.to_dict(),
        safe_click_box=safe_box,
        provenance="fresh_current_frame_proven_slot",
    )


def _require_live_contract(settings: Settings, store: SQLiteStore) -> None:
    if settings.execution_mode != "live" or not settings.allow_live_input:
        raise BuildPlacementLiveError(
            "V2.4E/F requires GOVERNOR_EXECUTION_MODE=live and GOVERNOR_ALLOW_LIVE_INPUT=true"
        )
    if not store.get_runtime("live_armed", False):
        raise BuildPlacementLiveError("V2.4E/F requires explicit live arming")


def _capture_snapshot(capture: ClientAreaCapture, backend: Win32WindowBackend, catalog: RegionCatalog):
    frame = capture.capture()
    snapshot = build_local_menu_snapshot(
        phase="category", frame=frame, capture=capture, backend=backend, catalog=catalog
    )
    return uuid4().hex, frame, snapshot


def _summary(frame_id: str, frame: Any, snapshot: BuildMenuSnapshot) -> dict[str, Any]:
    return {
        "frame_id": frame_id,
        "state": snapshot.state.value,
        "geometry": snapshot.geometry.to_dict() if snapshot.geometry else None,
        "options_found": len(snapshot.options),
        "close_control": snapshot.close_control,
        "placement_cancel": snapshot.placement_cancel,
        "capture": frame.diagnostic.to_dict() if frame.diagnostic else None,
    }


def run_live_build_placement_roundtrip(
    settings: Settings,
    store: SQLiteStore,
    *,
    output_dir: Path,
    window_title: str | None = None,
    evidence_path: Path = Path("data/probe/V2.4E0/result.json"),
    settle_seconds: float = 0.6,
) -> dict[str, Any]:
    """Attempt one option-select/placement-cancel roundtrip, at most two clicks."""
    if settle_seconds < 0:
        raise BuildPlacementLiveError("settle_seconds must be non-negative")
    output_dir.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "phase": "V2.4E/F",
        "max_option_clicks": 1,
        "max_cancel_clicks": 1,
        "option_clicks": 0,
        "cancel_clicks": 0,
        "clicks": 0,
        "retries": 0,
        "qwen_calls": 0,
        "qwen_flash_calls": 0,
        "qwen_max_calls": 0,
        "keyboard_inputs": 0,
        "map_clicks": 0,
        "save_writes": 0,
        "memory_writes": 0,
        "runtime_telemetry": False,
        "mono_debugger": False,
        "input_sent": False,
        "result": "FAIL",
    }
    try:
        proven_slot = _load_proven_slot(evidence_path)
        report["proven_slot_evidence"] = str(evidence_path)
        report["proven_slot_available"] = proven_slot is not None
        if proven_slot is None:
            raise BuildPlacementLiveError("FAIL_PRECONDITION_NO_PROVEN_SAFE_SLOT")
        _require_live_contract(settings, store)

        backend = Win32WindowBackend()
        window = _locate_window(settings, backend, window_title)
        info = window.locate()
        window.require_foreground(info)
        expected_pid = backend.window_process_id(info.hwnd)
        if expected_pid is None:
            raise BuildPlacementLiveError("Song HWND has no readable PID")
        capture = ClientAreaCapture(window, WindowsGraphicsCaptureBackend(), reject_near_black=True)
        catalog = RegionCatalog()
        baseline_id, baseline_frame, baseline = _capture_snapshot(capture, backend, catalog)
        if baseline.state is not BuildMenuState.CATEGORY_OPEN:
            raise BuildPlacementLiveError(f"pre_state must be CATEGORY_OPEN, got {baseline.state.value}")
        if baseline.geometry is None or baseline.geometry.hwnd != info.hwnd or baseline.geometry.pid != expected_pid:
            raise BuildPlacementLiveError("TARGET_STALE: category frame identity does not match Song")
        geometry_matches, current_geometry = _frame_matches_window(baseline.geometry, window, info)
        if not geometry_matches:
            raise BuildPlacementLiveError("TARGET_STALE: category geometry changed before input")
        report["pre_state"] = baseline.state.value
        report["precondition"] = _summary(baseline_id, baseline_frame, baseline)
        plan = plan_build_option_click(baseline, frame_id=baseline_id, proven_slot=proven_slot)
        report["option_target"] = plan.to_dict()

        adapter = WindowsSendInputAdapter(
            window,
            Win32SendInputBackend(),
            enabled=True,
            allow_clicks=True,
            allow_keyboard=False,
            expected_pid=expected_pid,
            auto_foreground=False,
            safety_mode=InputSafetyMode.NORMAL,
        )
        with adapter.action_transaction():
            transaction_info = window.require_foreground(window.locate())
            if backend.window_process_id(transaction_info.hwnd) != expected_pid:
                raise BuildPlacementLiveError("Song PID changed before BUILD_OPTION input")
            transaction_matches, transaction_geometry = _frame_matches_window(baseline.geometry, window, transaction_info)
            if not transaction_matches:
                raise BuildPlacementLiveError("TARGET_STALE: geometry changed before BUILD_OPTION input")
            option_result = adapter.execute(InputCommand(
                "click", plan.click_point[0], plan.click_point[1],
                geometry_snapshot=transaction_geometry, target_role="BUILD_OPTION",
            ))
        report["option_clicks"] = 1
        report["clicks"] = 1
        report["option_input"] = option_result
        if settle_seconds:
            time.sleep(settle_seconds)

        selected_id, selected_frame, selected_snapshot = _capture_snapshot(capture, backend, catalog)
        if selected_snapshot.geometry is None or selected_snapshot.geometry.to_dict() != baseline.geometry.to_dict():
            raise BuildPlacementLiveError("TARGET_STALE: selected frame geometry changed")
        evidence = analyze_placement_transition(
            baseline_frame.rgba, selected_frame.rgba,
            selected_frame.width, selected_frame.height,
            baseline, selected_snapshot, catalog,
        )
        placement = placement_snapshot(evidence, geometry=selected_snapshot.geometry, frame_id=selected_id)
        target = evidence.cancel_target
        if target is not None:
            target = {
                **target,
                "frame_id": selected_id,
                "hwnd": selected_snapshot.geometry.hwnd,
                "pid": selected_snapshot.geometry.pid,
                "geometry": selected_snapshot.geometry.to_dict(),
            }
        report["selected"] = _summary(selected_id, selected_frame, placement)
        report["placement_evidence"] = evidence.to_dict()
        if not evidence.placement_mode or placement.state is not BuildMenuState.BUILDING_SELECTED or target is None:
            raise BuildPlacementLiveError("FAIL_POSTCONDITION_BUILDING_SELECTED_NOT_CONFIRMED")
        validate_fresh_cancel_target(target, frame_id=selected_id, geometry=selected_snapshot.geometry, current_frame_id=selected_id)

        adapter.safety_mode = InputSafetyMode.PLACEMENT_CANCEL_ONLY
        cancel_bbox = target.get("global_bbox", target.get("bbox"))
        if not isinstance(cancel_bbox, list) or len(cancel_bbox) != 4:
            raise BuildPlacementLiveError("fresh placement cancel target has no bbox")
        cancel_box = _safe_center(tuple(float(item) for item in cancel_bbox))
        cancel_point = ((cancel_box[0] + cancel_box[2]) / 2.0, (cancel_box[1] + cancel_box[3]) / 2.0)
        with adapter.action_transaction():
            transaction_info = window.require_foreground(window.locate())
            if backend.window_process_id(transaction_info.hwnd) != expected_pid:
                raise BuildPlacementLiveError("Song PID changed before BUILD_PLACEMENT_CANCEL input")
            transaction_matches, transaction_geometry = _frame_matches_window(selected_snapshot.geometry, window, transaction_info)
            if not transaction_matches:
                raise BuildPlacementLiveError("TARGET_STALE: geometry changed before BUILD_PLACEMENT_CANCEL input")
            cancel_result = adapter.execute(InputCommand(
                "click", cancel_point[0], cancel_point[1],
                geometry_snapshot=transaction_geometry, target_role="BUILD_PLACEMENT_CANCEL",
            ))
        report["cancel_clicks"] = 1
        report["clicks"] = 2
        report["cancel_target"] = {**target, "click_point": list(cancel_point), "safe_click_box": list(cancel_box)}
        report["cancel_input"] = cancel_result
        if settle_seconds:
            time.sleep(settle_seconds)

        after_id, after_frame, after = _capture_snapshot(capture, backend, catalog)
        if after.geometry is None or after.geometry.to_dict() != baseline.geometry.to_dict():
            raise BuildPlacementLiveError("TARGET_STALE: post-cancel geometry changed")
        report["postcondition"] = _summary(after_id, after_frame, after)
        report["post_state"] = after.state.value
        report["options_found"] = len(after.options)
        if after.state is not BuildMenuState.CATEGORY_OPEN:
            raise BuildPlacementLiveError(f"FAIL_POSTCONDITION_CANCEL_STATE_{after.state.value.upper()}")
        if detect_current_frame_cancel_controls(after_frame.rgba, after_frame.width, after_frame.height, catalog):
            raise BuildPlacementLiveError("FAIL_POSTCONDITION_PLACEMENT_CANCEL_STILL_PRESENT")
        report["build_count_verification"] = "UNKNOWN_NO_SAVE_COMPARISON"
        report["actual_buildings_placed"] = 0
        report["game_responsive_after"] = True
        report["result"] = "PASS"
    except (BuildPlacementLiveError, BuildMenuCalibrationError, CaptureError, InputError, WindowError, OSError, ValueError) as exc:
        text = str(exc)
        report["failure_class"] = text.split(":", 1)[0] if text.startswith("FAIL_") else type(exc).__name__
        report["failure_reason"] = text
    except Exception as exc:  # noqa: BLE001 - always persist and disarm this guarded path.
        report["failure_class"] = type(exc).__name__
        report["failure_reason"] = str(exc)
    finally:
        store.set_runtime("live_armed", False)
        report["arm_live"] = False
        report["input_sent"] = report["clicks"] > 0
        (output_dir / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report
