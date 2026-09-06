from __future__ import annotations

import time
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from .actions import ActionEngine
from .capture import ClientAreaCapture, WindowsGraphicsCaptureBackend
from .config import Settings
from .deepseek import DeepSeekClient, DeepSeekConfigurationError
from .models import ActionPlan, PlannedAction, RegionSpec
from .perception import PerceptionEngine, RegionCatalog
from .storage import SQLiteStore
from .window import ForegroundTimeout, SteamWindowAdapter, Win32WindowBackend, WindowError, WindowNotFound


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
                "canonical_id": item.get("canonical_id", item.get("id")),
                "raw_id": item.get("raw_id"),
                "role": item.get("role", "UNKNOWN"),
                "label": item.get("label"),
                "bbox": item.get("bbox"),
                "global_bbox": item.get("global_bbox"),
                "confidence": item.get("confidence", data.get("confidence")),
            }
            for item in elements
            if isinstance(item, dict)
        ]
    return summary


def _find_preflight_element(
    observations: dict[str, dict[str, Any]],
    element_ids: tuple[str, ...],
    roles: tuple[str, ...] = (),
) -> dict[str, Any]:
    for region, data in observations.items():
        elements = data.get("ui_elements", [])
        for element in elements:
            if not isinstance(element, dict):
                continue
            if element.get("id") in element_ids or element.get("canonical_id") in element_ids or element.get("role") in roles:
                return {
                    "found": True,
                    "region": region,
                    "id": element.get("canonical_id", element.get("id")),
                    "canonical_id": element.get("canonical_id", element.get("id")),
                    "raw_id": element.get("raw_id"),
                    "role": element.get("role"),
                    "label": element.get("label"),
                    "global_bbox": element.get("global_bbox"),
                    "confidence": element.get("confidence", data.get("confidence")),
                }
    return {
        "found": False,
        "region": None,
        "id": element_ids[0],
        "canonical_id": None,
        "raw_id": None,
        "role": None,
        "label": None,
        "global_bbox": None,
        "confidence": None,
    }


def _calibration_candidate(element: dict[str, Any], region: str) -> dict[str, Any]:
    return {
        "role": element.get("role", "UNKNOWN"),
        "canonical_id": element.get("canonical_id", element.get("id")),
        "raw_id": element.get("raw_id", element.get("id")),
        "label": element.get("label"),
        "region": region,
        "bbox": element.get("bbox"),
        "global_bbox": element.get("global_bbox"),
        "confidence": element.get("confidence"),
    }


def _candidate_decision(candidate: dict[str, Any]) -> str:
    confidence = candidate.get("confidence")
    if not isinstance(confidence, (int, float)):
        return "REJECT"
    if confidence >= 0.90:
        return "ACCEPT"
    if confidence >= 0.70:
        return "SECOND_VISION_PASS_REQUIRED"
    return "REJECT"


def _select_calibration_candidate(
    observation: dict[str, Any],
    state: str,
    region: str,
    *,
    allow_second_vision: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    allowed = {
        # In the open state we calibrate the control that can close the menu;
        # in the closed state we calibrate the control that can open it.
        "open": {"BUILD_MENU_TOGGLE", "BUILD_MENU_CLOSE"},
        "closed": {"BUILD_MENU_TOGGLE", "BUILD_MENU_OPEN"},
    }[state]
    candidates: list[dict[str, Any]] = []
    for item in observation.get("ui_elements", []):
        if not isinstance(item, dict):
            continue
        candidate = _calibration_candidate(item, region)
        candidate["decision"] = _candidate_decision(candidate)
        if candidate["role"] in allowed:
            candidates.append(candidate)
    accepted = [
        item for item in candidates
        if item["decision"] == "ACCEPT" or (allow_second_vision and item["decision"] == "SECOND_VISION_PASS_REQUIRED")
    ]
    accepted.sort(key=lambda item: float(item.get("confidence", 0)), reverse=True)
    return candidates, accepted[0] if accepted else None


def _bbox_iou(first: list[float] | None, second: list[float] | None) -> float:
    if not isinstance(first, list) or not isinstance(second, list) or len(first) != 4 or len(second) != 4:
        return 0.0
    left = max(first[0], second[0])
    top = max(first[1], second[1])
    right = min(first[2], second[2])
    bottom = min(first[3], second[3])
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    area_first = max(0.0, first[2] - first[0]) * max(0.0, first[3] - first[1])
    area_second = max(0.0, second[2] - second[0]) * max(0.0, second[3] - second[1])
    union = area_first + area_second - intersection
    return intersection / union if union else 0.0


def _bbox_within_region(bbox: Any, region: RegionSpec, *, epsilon: float = 1e-6) -> bool:
    """Return whether a normalized full-client bbox fits inside a formal ROI."""
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        return False
    try:
        left, top, right, bottom = (float(value) for value in bbox)
    except (TypeError, ValueError):
        return False
    if not 0 <= left < right <= 1 or not 0 <= top < bottom <= 1:
        return False
    return (
        left >= region.left - epsilon
        and top >= region.top - epsilon
        and right <= region.right + epsilon
        and bottom <= region.bottom + epsilon
    )


def _runtime_region_for_state(state: str) -> str:
    """Return the formal ROI for the control visible in a calibration state."""
    if state == "closed":
        return "build_entry"
    if state == "open":
        return "build_controls"
    raise E2EPreflightError("calibration state must be open or closed")


def _runtime_role_is_compatible(actual: Any, expected: Any) -> bool:
    return actual == expected or (expected == "BUILD_MENU_OPEN" and actual == "BUILD_MENU_TOGGLE") or (
        expected == "BUILD_MENU_CLOSE" and actual == "BUILD_MENU_TOGGLE"
    )


def _canonical_control_is_compatible(actual: Any, expected: Any, expected_role: str) -> bool:
    if actual == expected:
        return True
    if expected_role == "BUILD_MENU_OPEN":
        return {actual, expected}.issubset({"build_menu_toggle", "build_menu_open_control"})
    if expected_role == "BUILD_MENU_CLOSE":
        return {actual, expected}.issubset({"build_menu_toggle", "build_menu_close_control"})
    return False


def calibrated_runtime_regions(calibration: dict[str, Any]) -> tuple[str, ...]:
    """Build the runtime ROI set from validated calibration, never from guesses."""
    if not calibration.get("live_e2e_ready") or not calibration.get("runtime_resolvable"):
        raise E2EConfigurationError("build-menu calibration is not runtime-resolvable")
    regions = {"resources", "events", "dialog"}
    for target_name in ("open", "close"):
        target = calibration.get(target_name)
        if not isinstance(target, dict) or not isinstance(target.get("region"), str) or not target["region"].strip():
            raise E2EConfigurationError(f"calibrated {target_name} target has no formal runtime region")
        regions.add(target["region"].strip())
    return tuple(sorted(regions))


def _runtime_target_valid(target: Any, catalog: RegionCatalog, *, expected_role: str) -> bool:
    if not isinstance(target, dict):
        return False
    region_name = target.get("region")
    if not isinstance(region_name, str) or not region_name.strip():
        return False
    try:
        region = catalog.get(region_name)
    except KeyError:
        return False
    confidence = target.get("confidence")
    return (
        target.get("canonical_id") in {"build_menu_open_control", "build_menu_close_control", "build_menu_toggle"}
        and _runtime_role_is_compatible(target.get("role"), expected_role)
        and isinstance(confidence, (int, float))
        and confidence >= 0.90
        and _bbox_within_region(target.get("global_bbox"), region)
        and bool(target.get("runtime_resolvable", False))
    )


def finalize_build_menu_calibration(output_dir: Path) -> dict[str, Any]:
    """Combine independently captured open/closed states without storing pixels."""
    open_path = output_dir / "build_menu_open_calibration.json"
    closed_path = output_dir / "build_menu_closed_calibration.json"
    if not open_path.exists() or not closed_path.exists():
        return {"live_e2e_ready": False, "reason": "both open and closed calibrations are required"}
    opened = json.loads(open_path.read_text(encoding="utf-8"))
    closed = json.loads(closed_path.read_text(encoding="utf-8"))
    # The open-state frame exposes the control that closes the menu; the
    # closed-state frame exposes the control that opens it.
    close_target = opened.get("selected_target")
    open_target = closed.get("selected_target")
    result: dict[str, Any] = {
        "resolution": opened.get("resolution"),
        "control_mode": None,
        "open": None,
        "close": None,
        "validated_states": {
            "closed": closed.get("build_menu_open") is False and bool(closed.get("calibration_pass")),
            "open": opened.get("build_menu_open") is True and bool(opened.get("calibration_pass")),
        },
        "runtime_resolvable": False,
        "live_e2e_ready": False,
    }
    catalog = RegionCatalog()
    if not open_target or not close_target or not all(result["validated_states"].values()):
        result["reason"] = "one or both state calibrations are incomplete"
        return result
    # The closed frame provides the OPEN target and the open frame provides the
    # CLOSE target.  Their state artifacts must already contain a successful
    # second Vision pass through their formal runtime ROI.
    if not _runtime_target_valid(open_target, catalog, expected_role="BUILD_MENU_OPEN"):
        result["reason"] = "closed-state OPEN target is not runtime-resolvable"
        return result
    if not _runtime_target_valid(close_target, catalog, expected_role="BUILD_MENU_CLOSE"):
        result["reason"] = "open-state CLOSE target is not runtime-resolvable"
        return result
    overlap = _bbox_iou(open_target.get("global_bbox"), close_target.get("global_bbox"))
    matching_role = open_target.get("role") == close_target.get("role")
    if overlap >= 0.70 and matching_role:
        result["control_mode"] = "TOGGLE"
        result["open"] = {"region": open_target["region"], "canonical_id": open_target["canonical_id"], "role": open_target["role"]}
        result["close"] = {"region": close_target["region"], "canonical_id": close_target["canonical_id"], "role": close_target["role"]}
    elif open_target.get("role") in {"BUILD_MENU_OPEN", "BUILD_MENU_TOGGLE"} and close_target.get("role") in {"BUILD_MENU_CLOSE", "BUILD_MENU_TOGGLE"}:
        result["control_mode"] = "SEPARATE"
        result["open"] = {"region": open_target["region"], "canonical_id": open_target["canonical_id"], "role": open_target["role"]}
        result["close"] = {"region": close_target["region"], "canonical_id": close_target["canonical_id"], "role": close_target["role"]}
    else:
        result["reason"] = "open and close targets have no validated toggle or separate semantic mapping"
        return result
    result["runtime_resolvable"] = True
    result["live_e2e_ready"] = True
    (output_dir / "build_menu_calibration.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def calibrate_build_menu_state(
    settings: Settings,
    store: SQLiteStore,
    *,
    state: str,
    output_dir: Path = Path("data/e2e"),
    window_title: str | None = None,
) -> dict[str, Any]:
    """Read-only calibration for one explicit build-menu state."""
    if state not in {"open", "closed"}:
        raise E2EPreflightError("calibration state must be open or closed")
    if not settings.deepseek_api_key:
        raise DeepSeekConfigurationError("DEEPSEEK_API_KEY is not configured")
    if not settings.deepseek_vision_model:
        raise DeepSeekConfigurationError("DEEPSEEK_VISION_MODEL is not configured")
    output_dir.mkdir(parents=True, exist_ok=True)
    window_backend = Win32WindowBackend()
    selected_title = window_title or settings.game_window_title
    window = SteamWindowAdapter(selected_title, window_backend)
    try:
        info = window.locate()
    except WindowNotFound:
        if window_title or selected_title == "Song":
            raise
        window = SteamWindowAdapter("Song", window_backend)
        info = window.locate()
    capture = ClientAreaCapture(window, WindowsGraphicsCaptureBackend())
    frame = capture.capture()
    client = DeepSeekClient(
        settings.deepseek_api_base,
        settings.deepseek_api_key,
        settings.deepseek_vision_model,
        usage_callback=store.record_token_usage,
    )
    perception = PerceptionEngine(client, RegionCatalog(), model=settings.deepseek_vision_model)
    catalog = RegionCatalog()
    runtime_region_name = _runtime_region_for_state(state)
    runtime_region = catalog.get(runtime_region_name)
    regions_checked = [runtime_region_name]
    observation = perception.observe_rgba(
        frame.rgba,
        frame.width,
        frame.height,
        runtime_region_name,
        context=(
            f"只读建筑菜单校准，当前目标状态={state}；必须识别建筑菜单控制语义 role，不执行任何操作。"
            "只在当前正式校准 ROI 内识别控件，不要猜测 ROI 外的坐标。"
        ),
    )
    expected_open = state == "open"
    state_matches = observation.data.get("build_menu_open") is expected_open
    candidates, selected = _select_calibration_candidate(
        observation.data,
        state,
        runtime_region_name,
        allow_second_vision=True,
    )
    fallback_used = False
    full_client_vision: dict[str, Any] | None = None
    selected_source_region: str | None = runtime_region_name if selected else None
    if selected is None:
        fallback_used = True
        regions_checked.append("full_client")
        full_region = RegionSpec(
            "full_client",
            0.0,
            0.0,
            1.0,
            1.0,
            "校准模式：扫描完整游戏客户区，只寻找建筑菜单控制，不分析地图。"
            "当前是 closed 时，优先检查右上角和界面边缘可打开建筑菜单的入口按钮；"
            "如果确实看不到控制，返回空数组，不要猜测坐标。",
        )
        full_observation = perception.observe_custom_rgba(
            frame.rgba,
            frame.width,
            frame.height,
            full_region,
            context=f"只读建筑菜单全客户区校准，当前目标状态={state}；只寻找 BUILD_MENU_TOGGLE/OPEN/CLOSE，不执行任何操作",
        )
        if full_observation.data.get("build_menu_open") is expected_open:
            state_matches = True
        full_client_vision = _preflight_observation_summary(full_observation.data)
        full_candidates, full_selected = _select_calibration_candidate(
            full_observation.data,
            state,
            "full_client",
            allow_second_vision=True,
        )
        candidates.extend(full_candidates)
        selected = full_selected
        selected_source_region = "full_client" if selected else None

    source_selected_target = dict(selected) if selected else None
    runtime_resolution: dict[str, Any] = {
        "region": runtime_region_name,
        "found": False,
        "canonical_id": None,
        "role": None,
        "global_bbox": None,
        "confidence": None,
        "source_region": selected_source_region,
        "runtime_resolvable": False,
    }
    runtime_selected: dict[str, Any] | None = None
    runtime_region_missing = False
    if selected is not None:
        if not _bbox_within_region(selected.get("global_bbox"), runtime_region):
            runtime_region_missing = True
        else:
            # Always confirm the candidate through the formal runtime ROI. The
            # full-client pass is discovery-only and never becomes an input target.
            runtime_observation = perception.observe_rgba(
                frame.rgba,
                frame.width,
                frame.height,
                runtime_region_name,
                context=(
                    f"只读建筑菜单运行时目标复核，当前状态={state}；"
                    "只确认正式 ROI 内的同一建筑菜单控件，不执行任何操作。"
                ),
            )
            runtime_candidates, runtime_candidate = _select_calibration_candidate(
                runtime_observation.data,
                state,
                runtime_region_name,
                allow_second_vision=True,
            )
            runtime_resolution["vision"] = _preflight_observation_summary(runtime_observation.data)
            if runtime_candidate is not None:
                runtime_resolution.update({
                    "found": True,
                    "canonical_id": runtime_candidate.get("canonical_id"),
                    "role": runtime_candidate.get("role"),
                    "global_bbox": runtime_candidate.get("global_bbox"),
                    "confidence": runtime_candidate.get("confidence"),
                })
                same_control = _canonical_control_is_compatible(
                    runtime_candidate.get("canonical_id"),
                    selected.get("canonical_id"),
                    "BUILD_MENU_OPEN" if state == "closed" else "BUILD_MENU_CLOSE",
                )
                compatible_role = _runtime_role_is_compatible(runtime_candidate.get("role"), selected.get("role"))
                high_confidence = isinstance(runtime_candidate.get("confidence"), (int, float)) and runtime_candidate["confidence"] >= 0.90
                if same_control and compatible_role and high_confidence:
                    runtime_selected = dict(runtime_candidate)
                    runtime_selected["region"] = runtime_region_name
                    runtime_selected["runtime_resolvable"] = True
                    runtime_selected["source_region"] = selected_source_region
                    runtime_resolution["runtime_resolvable"] = True
                else:
                    runtime_resolution["reason"] = "formal ROI resolved a different or low-confidence control"
            else:
                runtime_resolution["reason"] = "formal ROI did not resolve the calibrated control"
    if runtime_region_missing:
        runtime_resolution["reason"] = "calibrated target bbox is outside its formal runtime ROI"
    result: dict[str, Any] = {
        "state": state,
        "build_menu_open": observation.data.get("build_menu_open"),
        "state_matches": state_matches,
        "resolution": [frame.width, frame.height],
        "game_hwnd": info.hwnd,
        "game_pid": window_backend.window_process_id(info.hwnd),
        "capture": frame.diagnostic.to_dict() if frame.diagnostic else None,
        "vision_regions_checked": regions_checked,
        "full_client_fallback": fallback_used,
        "vision": _preflight_observation_summary(observation.data),
        "full_client_vision": full_client_vision,
        "candidates": candidates,
        "source_selected_target": source_selected_target,
        "selected_target": runtime_selected,
        "runtime_region": runtime_region_name,
        "runtime_region_missing": runtime_region_missing,
        "runtime_resolution": runtime_resolution,
        "runtime_resolvable": bool(runtime_resolution["runtime_resolvable"]),
        "calibration_pass": bool(state_matches and runtime_selected),
        "live_e2e_ready": False,
    }
    path = output_dir / f"build_menu_{state}_calibration.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if state == "closed" and result["calibration_pass"]:
        combined = finalize_build_menu_calibration(output_dir)
        result["combined_calibration"] = combined
    return result


def resolve_build_menu_target(
    settings: Settings,
    store: SQLiteStore,
    *,
    state: str,
    output_dir: Path = Path("data/e2e"),
    window_title: str | None = None,
) -> dict[str, Any]:
    """Resolve one calibrated target from the current frame without input."""
    if state not in {"open", "closed"}:
        raise E2EPreflightError("resolver state must be open or closed")
    if not settings.deepseek_api_key:
        raise DeepSeekConfigurationError("DEEPSEEK_API_KEY is not configured")
    if not settings.deepseek_vision_model:
        raise DeepSeekConfigurationError("DEEPSEEK_VISION_MODEL is not configured")
    output_dir.mkdir(parents=True, exist_ok=True)
    calibration_path = output_dir / "build_menu_calibration.json"
    if not calibration_path.exists():
        raise E2EConfigurationError("build_menu_calibration.json is missing")
    try:
        calibration = json.loads(calibration_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise E2EConfigurationError("build_menu_calibration.json is invalid") from exc
    regions = calibrated_runtime_regions(calibration)
    target_name = "open" if state == "closed" else "close"
    target = calibration.get(target_name)
    if not isinstance(target, dict):
        raise E2EConfigurationError(f"calibrated {target_name} target is missing")
    region_name = target.get("region")
    canonical_id = target.get("canonical_id")
    expected_role = "BUILD_MENU_OPEN" if state == "closed" else "BUILD_MENU_CLOSE"
    if not isinstance(region_name, str) or region_name not in regions or not isinstance(canonical_id, str):
        raise E2EConfigurationError("calibrated target has no valid runtime region or canonical ID")

    backend = Win32WindowBackend()
    selected_title = window_title or settings.game_window_title
    window = SteamWindowAdapter(selected_title, backend)
    try:
        try:
            info = window.locate()
        except WindowNotFound:
            if window_title or selected_title == "Song":
                raise
            window = SteamWindowAdapter("Song", backend)
            info = window.locate()
        capture = ClientAreaCapture(window, WindowsGraphicsCaptureBackend())
        frame = capture.capture()
    except WindowError as exc:
        raise E2EPreflightError(f"WINDOW_ERROR: {exc}") from exc
    diagnostic = frame.diagnostic.to_dict() if frame.diagnostic else {}
    if diagnostic.get("near_black_frame"):
        raise E2EPreflightError("CAPTURE_BLACK_FRAME")
    client = DeepSeekClient(
        settings.deepseek_api_base,
        settings.deepseek_api_key,
        settings.deepseek_vision_model,
        usage_callback=store.record_token_usage,
    )
    perception = PerceptionEngine(client, RegionCatalog(), model=settings.deepseek_vision_model)
    observation = perception.observe_rgba(
        frame.rgba,
        frame.width,
        frame.height,
        region_name,
        context=(
            f"只读建筑菜单运行时目标解析，当前状态={state}；只解析正式 ROI {region_name}，"
            "不要使用校准文件中的 bbox 或 raw_id，不执行任何操作。"
        ),
    )
    summary = _preflight_observation_summary(observation.data)
    found = None
    for element in summary.get("ui_elements", []):
        if not _canonical_control_is_compatible(element.get("canonical_id"), canonical_id, expected_role):
            continue
        if not _runtime_role_is_compatible(element.get("role"), expected_role):
            continue
        if not isinstance(element.get("confidence"), (int, float)) or element["confidence"] < 0.90:
            continue
        found = element
        break
    result = {
        "state": state,
        "target": target_name,
        "region": region_name,
        "canonical_id": canonical_id,
        "expected_role": expected_role,
        "found": found is not None,
        "element": found,
        "vision": summary,
        "capture": diagnostic,
        "window": {
            "hwnd": info.hwnd,
            "title": info.title,
            "client_width": info.client_width,
            "client_height": info.client_height,
        },
        "arm_live": False,
        "input_sent": False,
    }
    (output_dir / f"build_menu_resolve_{state}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return result


def run_read_only_preflight(
    settings: Settings,
    store: SQLiteStore,
    *,
    wait_for_game_foreground: bool = False,
    timeout_seconds: float = 30.0,
    stable_seconds: float = 3.0,
    poll_seconds: float = 0.5,
    output_dir: Path = Path("data/e2e"),
    window_title: str | None = None,
) -> dict[str, Any]:
    """Wait for the real game window and perform capture/Vision checks only."""
    if not settings.deepseek_api_key:
        raise DeepSeekConfigurationError("DEEPSEEK_API_KEY is not configured")
    if not settings.deepseek_vision_model:
        raise DeepSeekConfigurationError("DEEPSEEK_VISION_MODEL is not configured")

    output_dir.mkdir(parents=True, exist_ok=True)
    backend = Win32WindowBackend()
    selected_title = window_title or settings.game_window_title
    window = SteamWindowAdapter(selected_title, backend)
    try:
        if wait_for_game_foreground:
            info = window.wait_for_foreground(
                timeout_seconds=timeout_seconds,
                stable_seconds=stable_seconds,
                poll_seconds=poll_seconds,
            )
        else:
            # Read-only capture does not require the game to be foreground.
            # Live input keeps its separate exact-HWND guard in input.py.
            try:
                info = window.locate()
            except WindowNotFound:
                # Steam currently exposes the installed game as "Song" even
                # when the persisted user-facing title is the Chinese name.
                if window_title or selected_title == "Song":
                    raise
                window = SteamWindowAdapter("Song", backend)
                info = window.locate()
    except ForegroundTimeout as exc:
        raise E2EPreflightError("FOREGROUND_TIMEOUT") from exc
    except WindowError as exc:
        raise E2EPreflightError(f"FOREGROUND_ERROR: {exc}") from exc

    foreground = window.foreground_diagnostic(info)
    # Read-only preflight uses the same production WGC path so the Vision
    # evidence is not contaminated by GDI layered-window behavior.
    capture = ClientAreaCapture(window, WindowsGraphicsCaptureBackend())
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

    report_path = output_dir / "preflight_vision.json"
    report: dict[str, Any] = {
        "status": "CAPTURE_PASS",
        "capture_pass": True,
        "vision_pass": False,
        "open_target_ready": False,
        "close_target_ready": False,
        "action_target_calibrated": False,
        "live_e2e_ready": False,
        "wait_for_game_foreground": wait_for_game_foreground,
        "foreground_stable_seconds": stable_seconds if wait_for_game_foreground else None,
        "window": {
            "hwnd": info.hwnd,
            "title": info.title,
            "client_width": info.client_width,
            "client_height": info.client_height,
            "minimized": info.minimized,
        },
        "foreground": foreground.to_dict(),
        "capture": diagnostic,
        "vision": {},
        "elements": {},
        "live_input": {
            "arm_live_called": False,
            "input_sent": False,
        },
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

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
            report["status"] = "FAIL"
            report["vision_pass"] = False
            report["failure_class"] = "VISION_ERROR"
            report["failure_reason"] = f"{type(exc).__name__}: {exc}"
            report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            raise E2EPreflightError(f"VISION_ERROR: {type(exc).__name__}: {exc}") from exc
        observations[region_name] = _preflight_observation_summary(observation.data)

    report["vision_pass"] = True
    report["vision"] = observations
    report["elements"] = {
        "open": _find_preflight_element(
            observations,
            ("build_menu_open_control", "build_menu_toggle"),
            ("BUILD_MENU_OPEN", "BUILD_MENU_TOGGLE"),
        ),
        "close": _find_preflight_element(
            observations,
            ("build_menu_close_control", "build_menu_toggle"),
            ("BUILD_MENU_CLOSE", "BUILD_MENU_TOGGLE"),
        ),
    }
    report["open_target_ready"] = bool(report["elements"]["open"]["found"])
    report["close_target_ready"] = bool(report["elements"]["close"]["found"])
    calibration_path = output_dir / "build_menu_calibration.json"
    if calibration_path.exists():
        try:
            calibration = json.loads(calibration_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            calibration = {}
        report["action_target_calibrated"] = bool(
            calibration.get("live_e2e_ready") and calibration.get("runtime_resolvable")
        )
    report["live_e2e_ready"] = bool(report["action_target_calibrated"])
    report["status"] = "LIVE_E2E_READY" if report["live_e2e_ready"] else "ACTION_TARGET_CALIBRATION_PENDING"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


@dataclass
class BuildMenuE2EHarness:
    settings: Settings
    store: SQLiteStore
    actions: ActionEngine
    open_region: str | None = None
    open_element: str | None = None
    close_region: str | None = None
    close_element: str | None = None

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
        if not all((self.open_region, self.open_element, self.close_region, self.close_element)):
            raise E2EConfigurationError("open/close targets must come from a validated calibration")

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
            for phase, skill, element, region, expected in (
                ("open", "OPEN_BUILD_MENU", self.open_element, self.open_region, True),
                ("close", "CLOSE_BUILD_MENU", self.close_element, self.close_region, False),
            ):
                plan = ActionPlan(
                    reason=f"E2E-001 build menu {phase} cycle {index}",
                    actions=[PlannedAction(
                        skill,
                        {
                            "target_region": region,
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
