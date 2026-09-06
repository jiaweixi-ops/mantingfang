"""Manual, read-only V2.4E0 placement/cancel calibration workflow."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from .build_menu import BuildMenuState
from .build_menu_observer import BuildMenuCalibrationError, build_local_menu_snapshot
from .build_placement import (
    analyze_placement_transition,
    bbox_iou,
    detect_current_frame_cancel_controls,
    placement_snapshot,
    validate_fresh_cancel_target,
)
from .capture import CaptureError, ClientAreaCapture, WindowsGraphicsCaptureBackend
from .config import Settings
from .perception import RegionCatalog
from .storage import SQLiteStore
from .window import SteamWindowAdapter, Win32WindowBackend, WindowError, WindowNotFound


class BuildPlacementCalibrationError(RuntimeError):
    """Raised when a read-only placement phase cannot prove its state."""


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


def _geometry_key(snapshot: Any) -> tuple[Any, ...]:
    geometry = snapshot.geometry
    if geometry is None:
        return ()
    return (
        geometry.hwnd,
        geometry.pid,
        geometry.client_width,
        geometry.client_height,
        geometry.client_origin,
        geometry.dpi,
    )


def _summary(frame_id: str, snapshot: Any, frame: Any) -> dict[str, Any]:
    return {
        "frame_id": frame_id,
        "state": snapshot.state.value,
        "geometry": snapshot.geometry.to_dict() if snapshot.geometry else None,
        "options_found": len(snapshot.options),
        "categories_found": len(snapshot.categories),
        "close_control": snapshot.close_control,
        "placement_cancel": snapshot.placement_cancel,
        "capture": frame.diagnostic.to_dict() if frame.diagnostic else None,
    }


def _write(output_dir: Path, report: dict[str, Any]) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "result.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report


def run_read_only_placement_calibration(
    settings: Settings,
    store: SQLiteStore,
    *,
    output_dir: Path,
    window_title: str | None = None,
    settle_seconds: float = 0.35,
) -> dict[str, Any]:
    """Run the two manual checkpoints; this function never sends input."""
    if settle_seconds < 0:
        raise BuildPlacementCalibrationError("settle_seconds must be non-negative")
    report: dict[str, Any] = {
        "phase": "V2.4E0",
        "pre_state": "unknown",
        "manual_build_option_clicks": 0,
        "automated_build_option_clicks": 0,
        "placement_state_detected": False,
        "placement_confidence": 0.0,
        "cancel_target_detected": False,
        "cancel_confidence": 0.0,
        "post_manual_cancel_state": "unknown",
        "actual_buildings_placed": 0,
        "sendinput_calls": 0,
        "automated_mouse_clicks": 0,
        "keyboard_inputs": 0,
        "map_clicks": 0,
        "qwen_calls": 0,
        "save_writes": 0,
        "memory_writes": 0,
        "runtime_telemetry": False,
        "mono_debugger": False,
        "safety_mode": "NORMAL",
        "result": "FAIL_SAFE_PLACEMENT_UNKNOWN",
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        backend = Win32WindowBackend()
        window = _locate_window(settings, backend, window_title)
        capture = ClientAreaCapture(window, WindowsGraphicsCaptureBackend(), reject_near_black=True)
        catalog = RegionCatalog()

        baseline_frame = capture.capture()
        baseline_id = uuid4().hex
        baseline = build_local_menu_snapshot(
            phase="category", frame=baseline_frame, capture=capture, backend=backend, catalog=catalog
        )
        if baseline.state is not BuildMenuState.CATEGORY_OPEN:
            raise BuildPlacementCalibrationError(
                f"V2.4E0 requires CATEGORY_OPEN baseline, got {baseline.state.value}"
            )
        if baseline.geometry is None or not baseline.options or baseline.close_control is None:
            raise BuildPlacementCalibrationError("CATEGORY_OPEN baseline lacks current close control or options")
        report["pre_state"] = baseline.state.value
        report["baseline"] = _summary(baseline_id, baseline, baseline_frame)

        print("请手动点击一个当前可选择的普通建筑卡片；点击后不要在地图上点击任何位置。")
        input("完成手动选择后按 Enter 继续只读检查：")
        report["manual_build_option_clicks"] = 1
        report["actual_buildings_placed_basis"] = "manual_selection_only_no_map_click_observed_by_workflow"
        if settle_seconds:
            time.sleep(settle_seconds)

        selected_frame = capture.capture()
        selected_id = uuid4().hex
        selected_snapshot = build_local_menu_snapshot(
            phase="category", frame=selected_frame, capture=capture, backend=backend, catalog=catalog
        )
        if selected_snapshot.geometry is None or _geometry_key(selected_snapshot) != _geometry_key(baseline):
            raise BuildPlacementCalibrationError("placement frame geometry/HWND/PID changed from baseline")
        evidence = analyze_placement_transition(
            baseline_frame.rgba,
            selected_frame.rgba,
            selected_frame.width,
            selected_frame.height,
            baseline,
            selected_snapshot,
            catalog,
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
        if not evidence.placement_mode or target is None or placement.state is not BuildMenuState.BUILDING_SELECTED:
            report["selected"] = _summary(selected_id, placement, selected_frame)
            report["placement_evidence"] = evidence.to_dict()
            report["failure_class"] = "FAIL_SAFE_PLACEMENT_UNKNOWN"
            report["failure_reason"] = "current frame did not provide two independent placement signals and a fresh cancel control"
            return _write(output_dir, report)

        validate_fresh_cancel_target(
            target,
            frame_id=selected_id,
            geometry=selected_snapshot.geometry,
            current_frame_id=selected_id,
        )
        report["selected"] = _summary(selected_id, placement, selected_frame)
        report["placement_evidence"] = evidence.to_dict()
        report["placement_state_detected"] = True
        report["placement_confidence"] = evidence.confidence
        report["cancel_target_detected"] = True
        report["cancel_confidence"] = float(target["confidence"])
        report["cancel_target"] = target
        report["safety_mode"] = "PLACEMENT_CANCEL_ONLY"

        print("已识别待放置状态和当前帧取消控件。请手动执行取消，不要点击地图；完成后按 Enter。")
        input("手动取消完成后按 Enter 继续只读检查：")
        if settle_seconds:
            time.sleep(settle_seconds)

        after_frame = capture.capture()
        after_id = uuid4().hex
        after_snapshot = build_local_menu_snapshot(
            phase="category", frame=after_frame, capture=capture, backend=backend, catalog=catalog
        )
        if after_snapshot.geometry is None or _geometry_key(after_snapshot) != _geometry_key(baseline):
            raise BuildPlacementCalibrationError("post-cancel geometry/HWND/PID changed from baseline")
        baseline_cancel = detect_current_frame_cancel_controls(
            baseline_frame.rgba, baseline_frame.width, baseline_frame.height, catalog
        )
        all_post_cancel_targets = detect_current_frame_cancel_controls(
            after_frame.rgba,
            after_frame.width,
            after_frame.height,
            catalog,
            excluded_bboxes=[item["bbox"] for item in baseline_cancel],
        )
        selected_cancel_bbox = target.get("bbox")
        placement_cancel_still_present = bool(
            isinstance(selected_cancel_bbox, list)
            and any(bbox_iou(selected_cancel_bbox, item.get("bbox", [])) >= 0.45 for item in all_post_cancel_targets)
        )
        post_cancel_targets = [
            item for item in all_post_cancel_targets
            if not isinstance(selected_cancel_bbox, list)
            or bbox_iou(selected_cancel_bbox, item.get("bbox", [])) < 0.45
        ]
        post_state = after_snapshot.state.value
        cleared = post_state in {BuildMenuState.CATEGORY_OPEN.value, BuildMenuState.ROOT_OPEN.value} and not post_cancel_targets
        report["post_manual_cancel_state"] = post_state
        report["post_cancel"] = _summary(after_id, after_snapshot, after_frame)
        report["post_cancel"]["new_cancel_targets"] = post_cancel_targets
        report["post_cancel"]["placement_cancel_still_present"] = placement_cancel_still_present
        report["placement_state_cleared"] = cleared
        report["actual_buildings_placed"] = 0
        if cleared:
            report["result"] = "PASS"
        else:
            report["failure_class"] = "FAIL_SAFE_CANCEL_UNKNOWN"
            report["failure_reason"] = "post-cancel frame still shows placement evidence or cannot be classified as CATEGORY_OPEN/ROOT_OPEN"
    except (BuildPlacementCalibrationError, BuildMenuCalibrationError, CaptureError, WindowError, OSError, ValueError, EOFError) as exc:
        report["failure_class"] = type(exc).__name__
        report["failure_reason"] = str(exc)
    except Exception as exc:  # noqa: BLE001 - read-only workflow must persist a bounded failure result.
        report["failure_class"] = type(exc).__name__
        report["failure_reason"] = str(exc)
    finally:
        _write(output_dir, report)
    return report
