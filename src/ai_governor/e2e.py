from __future__ import annotations

import time
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from .actions import ActionEngine
from .capture import CaptureError, ClientAreaCapture, WindowsGraphicsCaptureBackend, encode_rgba_png
from .config import Settings
from .qwen import QwenClient, QwenConfigurationError
from .input import InputCommand, WindowsSendInputAdapter, Win32SendInputBackend
from .models import ActionPlan, PlannedAction, RegionSpec
from .perception import PerceptionEngine, RegionCatalog
from .storage import SQLiteStore
from .window import ForegroundTimeout, SteamWindowAdapter, Win32WindowBackend, WindowError, WindowNotFound


class E2EConfigurationError(RuntimeError):
    pass


class E2EPreflightError(RuntimeError):
    pass


def _qwen_runtime_config(settings: Settings) -> tuple[str, str, str]:
    """Return the strictly configured Qwen Vision endpoint and model."""
    if not settings.qwen_api_key or not settings.qwen_vision_model:
        raise QwenConfigurationError("QWEN_API_KEY and QWEN_VISION_MODEL are not configured")
    return settings.qwen_api_base, settings.qwen_api_key, settings.qwen_vision_model


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
    api_base, api_key, vision_model = _qwen_runtime_config(settings)
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
    client = QwenClient(
        api_base,
        api_key,
        vision_model,
        usage_callback=store.record_token_usage,
    )
    perception = PerceptionEngine(client, RegionCatalog(), model=vision_model)
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
    api_base, api_key, vision_model = _qwen_runtime_config(settings)
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
    client = QwenClient(
        api_base,
        api_key,
        vision_model,
        usage_callback=store.record_token_usage,
    )
    perception = PerceptionEngine(client, RegionCatalog(), model=vision_model)
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


def _locate_game_window(settings: Settings, backend: Win32WindowBackend, window_title: str | None) -> SteamWindowAdapter:
    selected_title = window_title or settings.game_window_title
    window = SteamWindowAdapter(selected_title, backend)
    try:
        window.locate()
    except WindowNotFound:
        if window_title or selected_title == "Song":
            raise
        window = SteamWindowAdapter("Song", backend)
        window.locate()
    return window


def _roundtrip_element(
    observation: dict[str, Any],
    target: dict[str, Any],
    *,
    expected_role: str,
) -> dict[str, Any] | None:
    expected_id = target.get("canonical_id")
    if not isinstance(expected_id, str):
        return None
    for element in observation.get("ui_elements", []):
        if not isinstance(element, dict):
            continue
        if not _canonical_control_is_compatible(element.get("canonical_id"), expected_id, expected_role):
            continue
        if not _runtime_role_is_compatible(element.get("role"), expected_role):
            continue
        confidence = element.get("confidence")
        bbox = element.get("global_bbox")
        if not isinstance(confidence, (int, float)) or confidence < 0.90:
            continue
        if not _bbox_within_region(bbox, RegionCatalog().get(target["region"])):
            continue
        return element
    return None


def _close_only_runtime_target_candidates(calibrated_target: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    """Return formal current-frame ROI candidates for a close control.

    Older calibration captured the close semantic from ``build_controls``.
    Some live UI variants expose the actual close button in the upper-right
    ``build_entry`` ROI instead.  Both are formal catalog regions; this helper
    never carries a calibration bbox or invents coordinates.
    """
    candidates = [calibrated_target]
    if calibrated_target.get("region") == "build_controls":
        candidates.append({**calibrated_target, "region": "build_entry"})
    return tuple(candidates)


def _roundtrip_click_audit(
    info: Any,
    backend: Win32WindowBackend,
    element: dict[str, Any],
    calibrated_target: dict[str, Any],
) -> dict[str, Any]:
    bbox = element.get("global_bbox")
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        raise E2EPreflightError("click audit requires a current global_bbox")
    x_ratio = (float(bbox[0]) + float(bbox[2])) / 2
    y_ratio = (float(bbox[1]) + float(bbox[3])) / 2
    client_point = (round(info.client_width * x_ratio), round(info.client_height * y_ratio))
    screen_point = info.screen_point(x_ratio, y_ratio)
    dpi_getter = getattr(backend, "window_dpi", None)
    dpi = int(dpi_getter(info.hwnd)) if callable(dpi_getter) else 96
    observed_id = element.get("canonical_id") or element.get("id")
    calibrated_id = calibrated_target.get("canonical_id")
    calibrated_role = calibrated_target.get("role")
    compatibility_role = (
        "BUILD_MENU_OPEN"
        if calibrated_role in {"BUILD_MENU_TOGGLE", "BUILD_MENU_OPEN"}
        else calibrated_role
    )
    return {
        "bbox": [float(value) for value in bbox],
        "normalized_point": [x_ratio, y_ratio],
        "client_point": list(client_point),
        "screen_point": list(screen_point),
        "client_origin": [info.screen_left, info.screen_top],
        "dpi": dpi,
        "calibrated_target": {
            "region": calibrated_target.get("region"),
            "canonical_id": calibrated_id,
            "role": calibrated_target.get("role"),
        },
        "observed_target": {
            "id": element.get("id"),
            "canonical_id": observed_id,
            "raw_id": element.get("raw_id"),
            "role": element.get("role"),
            "label": element.get("label"),
            "confidence": element.get("confidence"),
        },
        "id_mapping": {
            "compatible": _canonical_control_is_compatible(observed_id, calibrated_id, compatibility_role),
            "reason": "semantic_role_compatibility" if observed_id != calibrated_id else "exact_canonical_id",
        },
    }


def _annotate_click_frame(frame: Any, audit: dict[str, Any], path: Path) -> None:
    """Write a diagnostic PNG; this never changes the game or sends input."""
    rgba = bytearray(frame.rgba)
    width, height = frame.width, frame.height
    bbox = audit["bbox"]
    left, top, right, bottom = [round(value) for value in (
        width * bbox[0], height * bbox[1], width * bbox[2], height * bbox[3]
    )]
    cx, cy = audit["client_point"]

    def pixel(x: int, y: int, color: tuple[int, int, int]) -> None:
        if 0 <= x < width and 0 <= y < height:
            offset = (y * width + x) * 4
            rgba[offset:offset + 4] = bytes((*color, 255))

    for x in range(left, right + 1):
        for y in (top, top + 1, bottom - 1, bottom):
            pixel(x, y, (255, 0, 0))
    for y in range(top, bottom + 1):
        for x in (left, left + 1, right - 1, right):
            pixel(x, y, (255, 0, 0))
    for x in range(max(0, cx - 16), min(width, cx + 17)):
        pixel(x, cy, (255, 255, 0))
    for y in range(max(0, cy - 16), min(height, cy + 17)):
        pixel(cx, y, (255, 255, 0))
    for y in range(max(0, cy - 5), min(height, cy + 6)):
        for x in range(max(0, cx - 5), min(width, cx + 6)):
            pixel(x, y, (255, 0, 0))
    path.write_bytes(encode_rgba_png(width, height, bytes(rgba)))


def _roundtrip_capture_and_observe(
    window: SteamWindowAdapter,
    backend: Win32WindowBackend,
    perception: PerceptionEngine,
    capture: ClientAreaCapture,
    frame_path: Path,
    target: dict[str, Any],
    *,
    expected_open: bool,
    phase: str,
    enforce_state: bool = True,
    require_target: bool = True,
) -> tuple[Any, Any, dict[str, Any], dict[str, Any], dict[str, Any]]:
    info = window.locate()
    foreground = window.foreground_diagnostic(info).to_dict()
    if not foreground["foreground_matches_game_hwnd"]:
        raise WindowError(f"foreground mismatch before {phase}: {foreground}")
    frame = capture.capture()
    frame_path.write_bytes(frame.png)
    diagnostic = frame.diagnostic.to_dict() if frame.diagnostic else {}
    if diagnostic.get("near_black_frame"):
        raise E2EPreflightError(f"CAPTURE_BLACK_FRAME during {phase}")
    observation = perception.observe_rgba(
        frame.rgba,
        frame.width,
        frame.height,
        target["region"],
        context=f"V2.3 Live E2E 只读{phase}前后验证；不分析地图，不执行额外操作",
    )
    dialog = None
    dialog_error: Exception | None = None
    for _ in range(2):
        try:
            dialog = perception.observe_rgba(
                frame.rgba,
                frame.width,
                frame.height,
                "dialog",
                context=(
                    f"V2.3 Live E2E {phase}异常弹窗检查；只读，不执行操作。"
                    "必须返回 dialog_open、current_screen、options、ui_elements 四个字段；"
                    "如果没有弹窗，dialog_open=false、options=[]、ui_elements=[]，不得省略字段。"
                ),
            )
            break
        except ValueError as exc:
            dialog_error = exc
    if dialog is None:
        raise E2EPreflightError(f"dialog vision schema invalid: {dialog_error}") from dialog_error
    if enforce_state and observation.data.get("build_menu_open") is not expected_open:
        raise E2EPreflightError(
            f"{phase} state precondition mismatch: expected build_menu_open={expected_open}"
        )
    if dialog.data.get("dialog_open") is True:
        raise E2EPreflightError(f"unexpected dialog during {phase}")
    element = _roundtrip_element(observation.data, target, expected_role="BUILD_MENU_OPEN" if not expected_open else "BUILD_MENU_CLOSE")
    if require_target and element is None:
        raise E2EPreflightError(f"calibrated target not resolved in current {phase} frame")
    return info, frame, observation.data, dialog.data, {
        "capture": diagnostic,
        "foreground": foreground,
        "element": element,
    }


def _roundtrip_pid_guard(window: SteamWindowAdapter, backend: Win32WindowBackend, expected_hwnd: int, expected_pid: int, phase: str):
    info = window.locate()
    if info.hwnd != expected_hwnd:
        raise WindowError(f"HWND changed during {phase}: expected={expected_hwnd}, actual={info.hwnd}")
    actual_pid = backend.window_process_id(info.hwnd)
    if actual_pid != expected_pid:
        raise WindowError(f"PID changed during {phase}: expected={expected_pid}, actual={actual_pid}")
    window.require_foreground(info)
    return info


def run_live_build_menu_roundtrip(
    settings: Settings,
    store: SQLiteStore,
    *,
    output_dir: Path = Path("data/e2e"),
    window_title: str | None = None,
    verify_timeout_seconds: float = 5.0,
    poll_seconds: float = 0.25,
    wait_for_game_foreground: bool = False,
    foreground_timeout_seconds: float = 30.0,
) -> dict[str, Any]:
    """Run exactly one closed->open->closed live roundtrip with no input retry."""
    if settings.execution_mode != "live" or not settings.allow_live_input:
        raise E2EConfigurationError("live roundtrip requires live mode and GOVERNOR_ALLOW_LIVE_INPUT=true")
    if not store.get_runtime("live_armed", False):
        raise E2EConfigurationError("live roundtrip requires explicit live arming")
    if verify_timeout_seconds <= 0 or poll_seconds <= 0:
        raise E2EConfigurationError("verification timings must be positive")
    output_dir.mkdir(parents=True, exist_ok=True)
    calibration_path = output_dir / "build_menu_calibration.json"
    if not calibration_path.exists():
        raise E2EConfigurationError("build_menu_calibration.json is missing")
    try:
        calibration = json.loads(calibration_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise E2EConfigurationError("build_menu_calibration.json is invalid") from exc
    regions = calibrated_runtime_regions(calibration)
    open_target = calibration.get("open")
    close_target = calibration.get("close")
    if not isinstance(open_target, dict) or not isinstance(close_target, dict):
        raise E2EConfigurationError("calibration does not contain open and close targets")
    report: dict[str, Any] = {
        "scenario": "build_menu_toggle_roundtrip",
        "pre_state": "closed",
        "open_action": {"input_sent": False},
        "open_verified": False,
        "close_action": {"input_sent": False},
        "close_verified": False,
        "total_inputs": 0,
        "unexpected_inputs": 0,
        "retry_input": False,
        "arm_live": True,
        "result": "FAIL",
    }
    try:
        backend = Win32WindowBackend()
        window = _locate_game_window(settings, backend, window_title)
        capture = ClientAreaCapture(window, WindowsGraphicsCaptureBackend(), reject_near_black=True)
        api_base, api_key, vision_model = _qwen_runtime_config(settings)
        client = QwenClient(
            api_base,
            api_key,
            vision_model,
            usage_callback=store.record_token_usage,
        )
        perception = PerceptionEngine(client, RegionCatalog(), model=vision_model)
        if wait_for_game_foreground:
            info = window.wait_for_foreground(
                timeout_seconds=foreground_timeout_seconds,
                stable_seconds=3.0,
                poll_seconds=0.5,
            )
        else:
            info = window.locate()
    except Exception as exc:  # noqa: BLE001 — persist a bounded failure artifact
        report["failure_class"] = type(exc).__name__
        report["failure_reason"] = str(exc)
        report["arm_live"] = bool(store.get_runtime("live_armed", False))
        report["input_sent"] = False
        (output_dir / "build_menu_roundtrip.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        raise
    expected_pid = backend.window_process_id(info.hwnd)
    if expected_pid is None:
        raise E2EPreflightError("game PID is unavailable")
    report["game"] = {"hwnd": info.hwnd, "pid": expected_pid, "resolution": [info.client_width, info.client_height]}
    adapter = WindowsSendInputAdapter(
        window,
        Win32SendInputBackend(),
        enabled=True,
        allow_clicks=True,
        allow_keyboard=False,
        expected_pid=expected_pid,
    )

    def verify_phase(
        target: dict[str, Any],
        expected_open: bool,
        phase: str,
        path_name: str,
        *,
        checkpoints_ms: tuple[int, ...] = (),
    ) -> dict[str, Any]:
        if checkpoints_ms:
            checkpoint_reports: list[dict[str, Any]] = []
            checkpoint_start = time.monotonic()
            for offset_ms in checkpoints_ms:
                remaining = checkpoint_start + (offset_ms / 1000) - time.monotonic()
                if remaining > 0:
                    time.sleep(remaining)
                checkpoint_path = output_dir / f"{Path(path_name).stem}_{offset_ms}ms.png"
                try:
                    current_info, _frame, observation, dialog, details = _roundtrip_capture_and_observe(
                        window,
                        backend,
                        perception,
                        capture,
                        checkpoint_path,
                        target,
                        expected_open=expected_open,
                        phase=f"{phase}_{offset_ms}ms",
                        enforce_state=False,
                        require_target=False,
                    )
                    current_pid = backend.window_process_id(current_info.hwnd)
                    if current_info.hwnd != info.hwnd or current_pid != expected_pid:
                        raise WindowError(f"window identity changed after {phase} at {offset_ms}ms")
                    element = _roundtrip_element(
                        observation,
                        target,
                        expected_role="BUILD_MENU_OPEN" if not expected_open else "BUILD_MENU_CLOSE",
                    )
                    state_match = observation.get("build_menu_open") is expected_open
                    checkpoint_reports.append({
                        "offset_ms": offset_ms,
                        "state": "open" if observation.get("build_menu_open") else "closed",
                        "state_match": state_match,
                        "capture": details["capture"],
                        "foreground": details["foreground"],
                        "vision": _preflight_observation_summary(observation),
                        "dialog": _preflight_observation_summary(dialog),
                        "element": element,
                        "screenshot": str(checkpoint_path),
                    })
                except (WindowError, CaptureError) as exc:
                    raise E2EPreflightError(
                        f"{phase} verification failed at {offset_ms}ms: {type(exc).__name__}: {exc}"
                    ) from exc
                except E2EPreflightError as exc:
                    checkpoint_reports.append({
                        "offset_ms": offset_ms,
                        "state_match": False,
                        "error": str(exc),
                        "screenshot": str(checkpoint_path),
                    })
            final = checkpoint_reports[-1] if checkpoint_reports else {}
            report.setdefault("post_click_verification", {})[phase] = {
                "expected_state": "open" if expected_open else "closed",
                "checkpoints": checkpoint_reports,
            }
            if not final.get("state_match") or not isinstance(final.get("element"), dict):
                raise E2EPreflightError(
                    f"{phase} verification failed after checkpoints: "
                    f"expected build_menu_open={expected_open}, checkpoints={checkpoint_reports}"
                )
            return {
                "state": "open" if expected_open else "closed",
                "capture": final["capture"],
                "foreground": final["foreground"],
                "vision": final["vision"],
                "dialog": final["dialog"],
                "element": final["element"],
                "checkpoints": checkpoint_reports,
                "verified": True,
            }
        deadline = time.monotonic() + verify_timeout_seconds
        last_error: str | None = None
        while True:
            try:
                current_info, frame, observation, dialog, details = _roundtrip_capture_and_observe(
                    window,
                    backend,
                    perception,
                    capture,
                    output_dir / path_name,
                    target,
                    expected_open=expected_open,
                    phase=phase,
                )
                current_pid = backend.window_process_id(current_info.hwnd)
                if current_info.hwnd != info.hwnd or current_pid != expected_pid:
                    raise WindowError(f"window identity changed after {phase}")
                return {
                    "state": "open" if expected_open else "closed",
                    "capture": details["capture"],
                    "foreground": details["foreground"],
                    "vision": _preflight_observation_summary(observation),
                    "dialog": _preflight_observation_summary(dialog),
                    "element": details["element"],
                    "verified": True,
                }
            except (WindowError, CaptureError) as exc:
                raise E2EPreflightError(f"{phase} verification failed: {type(exc).__name__}: {exc}") from exc
            except E2EPreflightError as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                if "state precondition mismatch" not in str(exc) and "calibrated target not resolved" not in str(exc):
                    raise
                if time.monotonic() >= deadline:
                    raise E2EPreflightError(f"{phase} verification failed: {last_error}") from exc
                time.sleep(poll_seconds)

    try:
        closed_before = verify_phase(open_target, False, "closed_before_open", "build_menu_roundtrip_closed_before.png")
        report["closed_before"] = closed_before
        open_element = closed_before["element"]
        open_input_info = _roundtrip_pid_guard(window, backend, info.hwnd, expected_pid, "open input")
        audit_frame = capture.capture()
        audit_diagnostic = audit_frame.diagnostic.to_dict() if audit_frame.diagnostic else {}
        if audit_diagnostic.get("near_black_frame"):
            raise E2EPreflightError("CAPTURE_BLACK_FRAME before open input audit")
        open_audit = _roundtrip_click_audit(open_input_info, backend, open_element, open_target)
        open_audit["source_screenshot"] = str(output_dir / "build_menu_roundtrip_open_click_source.png")
        open_audit["annotated_screenshot"] = str(output_dir / "build_menu_roundtrip_open_click_annotated.png")
        (output_dir / "build_menu_roundtrip_open_click_source.png").write_bytes(audit_frame.png)
        _annotate_click_frame(audit_frame, open_audit, output_dir / "build_menu_roundtrip_open_click_annotated.png")
        open_command = InputCommand(
            "click",
            (float(open_element["global_bbox"][0]) + float(open_element["global_bbox"][2])) / 2,
            (float(open_element["global_bbox"][1]) + float(open_element["global_bbox"][3])) / 2,
        )
        open_input_result = adapter.execute(open_command)
        report["total_inputs"] += 1
        report["open_action"] = {
            "canonical_id": open_element.get("canonical_id"),
            "role": open_element.get("role"),
            "confidence": open_element.get("confidence"),
            "global_bbox": open_element.get("global_bbox"),
            "click_audit": open_audit,
            "input_result": open_input_result,
            "input_sent": True,
        }
        opened = verify_phase(
            close_target,
            True,
            "open_after_click",
            "build_menu_roundtrip_open_after.png",
            checkpoints_ms=(200, 500, 1000, 2000),
        )
        report["open_verified"] = True
        report["open_after"] = opened

        close_input_info = _roundtrip_pid_guard(window, backend, info.hwnd, expected_pid, "close input")
        close_element = opened["element"]
        close_audit = _roundtrip_click_audit(close_input_info, backend, close_element, close_target)
        close_audit["annotated_screenshot"] = str(output_dir / "build_menu_roundtrip_close_click_annotated.png")
        close_frame = capture.capture()
        (output_dir / "build_menu_roundtrip_close_click_source.png").write_bytes(close_frame.png)
        close_audit["source_screenshot"] = str(output_dir / "build_menu_roundtrip_close_click_source.png")
        _annotate_click_frame(close_frame, close_audit, output_dir / "build_menu_roundtrip_close_click_annotated.png")
        close_command = InputCommand(
            "click",
            (float(close_element["global_bbox"][0]) + float(close_element["global_bbox"][2])) / 2,
            (float(close_element["global_bbox"][1]) + float(close_element["global_bbox"][3])) / 2,
        )
        close_input_result = adapter.execute(close_command)
        report["total_inputs"] += 1
        report["close_action"] = {
            "canonical_id": close_element.get("canonical_id"),
            "role": close_element.get("role"),
            "confidence": close_element.get("confidence"),
            "global_bbox": close_element.get("global_bbox"),
            "click_audit": close_audit,
            "input_result": close_input_result,
            "input_sent": True,
        }
        closed = verify_phase(
            open_target,
            False,
            "closed_after_click",
            "build_menu_roundtrip_closed_after.png",
            checkpoints_ms=(200, 500, 1000, 2000),
        )
        report["close_verified"] = True
        report["closed_after"] = closed
        report["result"] = "PASS"
    except Exception as exc:  # noqa: BLE001 — any uncertainty stops without retry
        report["failure_class"] = type(exc).__name__
        report["failure_reason"] = str(exc)
        report["result"] = "FAIL"
    finally:
        report["arm_live"] = bool(store.get_runtime("live_armed", False))
        report["input_sent"] = report["total_inputs"] > 0
        (output_dir / "build_menu_roundtrip.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return report


def run_live_build_menu_open_only(
    settings: Settings,
    store: SQLiteStore,
    *,
    output_dir: Path = Path("data/e2e/build_menu_open_only"),
    window_title: str | None = None,
    verify_timeout_seconds: float = 5.0,
    poll_seconds: float = 0.25,
    wait_for_game_foreground: bool = False,
    foreground_timeout_seconds: float = 30.0,
    checkpoints_ms: tuple[int, ...] = (200, 500, 1000, 2000),
) -> dict[str, Any]:
    """Run one guarded open-only click and never issue a close or placement input."""
    if settings.execution_mode != "live" or not settings.allow_live_input:
        raise E2EConfigurationError("open-only live diagnostic requires live mode and GOVERNOR_ALLOW_LIVE_INPUT=true")
    if not store.get_runtime("live_armed", False):
        raise E2EConfigurationError("open-only live diagnostic requires explicit live arming")
    if verify_timeout_seconds <= 0 or poll_seconds <= 0 or not checkpoints_ms:
        raise E2EConfigurationError("open-only verification timings must be positive")
    output_dir.mkdir(parents=True, exist_ok=True)
    calibration_path = output_dir.parent / "build_menu_calibration.json"
    if not calibration_path.exists():
        raise E2EConfigurationError("build_menu_calibration.json is missing")
    try:
        calibration = json.loads(calibration_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise E2EConfigurationError("build_menu_calibration.json is invalid") from exc
    calibrated_runtime_regions(calibration)
    open_target = calibration.get("open")
    close_target = calibration.get("close")
    if not isinstance(open_target, dict) or not isinstance(close_target, dict):
        raise E2EConfigurationError("calibration does not contain open and close targets")

    report: dict[str, Any] = {
        "scenario": "build_menu_open_only",
        "max_clicks": 1,
        "retry_input": False,
        "close_action": {"enabled": False, "input_sent": False},
        "placement_action": {"enabled": False, "input_sent": False},
        "total_inputs": 0,
        "unexpected_inputs": 0,
        "result": "FAIL",
    }

    try:
        backend = Win32WindowBackend()
        window = _locate_game_window(settings, backend, window_title)
        capture = ClientAreaCapture(window, WindowsGraphicsCaptureBackend(), reject_near_black=True)
        api_base, api_key, vision_model = _qwen_runtime_config(settings)
        client = QwenClient(
            api_base,
            api_key,
            vision_model,
            usage_callback=store.record_token_usage,
        )
        perception = PerceptionEngine(client, RegionCatalog(), model=vision_model)
        if wait_for_game_foreground:
            info = window.wait_for_foreground(
                timeout_seconds=foreground_timeout_seconds,
                stable_seconds=3.0,
                poll_seconds=0.5,
            )
        else:
            info = window.locate()
        expected_pid = backend.window_process_id(info.hwnd)
        if expected_pid is None:
            raise E2EPreflightError("game PID is unavailable")
        report["game"] = {
            "hwnd": info.hwnd,
            "pid": expected_pid,
            "resolution": [info.client_width, info.client_height],
        }
        adapter = WindowsSendInputAdapter(
            window,
            Win32SendInputBackend(),
            enabled=True,
            allow_clicks=True,
            allow_keyboard=False,
            expected_pid=expected_pid,
        )

        deadline = time.monotonic() + verify_timeout_seconds
        while True:
            try:
                before_info, before_frame, before_observation, before_dialog, before_details = _roundtrip_capture_and_observe(
                    window,
                    backend,
                    perception,
                    capture,
                    output_dir / "before.png",
                    open_target,
                    expected_open=False,
                    phase="open_only_before",
                )
                if before_info.hwnd != info.hwnd or backend.window_process_id(before_info.hwnd) != expected_pid:
                    raise WindowError("window identity changed before open-only input")
                break
            except E2EPreflightError as exc:
                if "state precondition mismatch" not in str(exc) and "calibrated target not resolved" not in str(exc):
                    raise
                if time.monotonic() >= deadline:
                    raise E2EPreflightError(f"open-only precondition failed: {exc}") from exc
                time.sleep(poll_seconds)
        report["precondition"] = {
            "build_menu_open": False,
            "capture": before_details["capture"],
            "foreground": before_details["foreground"],
            "vision": _preflight_observation_summary(before_observation),
            "dialog": _preflight_observation_summary(before_dialog),
            "element": before_details["element"],
        }
        input_info = _roundtrip_pid_guard(window, backend, info.hwnd, expected_pid, "open-only input")
        audit_frame = capture.capture()
        diagnostic = audit_frame.diagnostic.to_dict() if audit_frame.diagnostic else {}
        if diagnostic.get("near_black_frame"):
            raise E2EPreflightError("CAPTURE_BLACK_FRAME before open-only input")
        audit = _roundtrip_click_audit(input_info, backend, before_details["element"], open_target)
        audit["source_screenshot"] = str(output_dir / "before_click_source.png")
        audit["annotated_screenshot"] = str(output_dir / "before_annotated.png")
        (output_dir / "before_click_source.png").write_bytes(audit_frame.png)
        _annotate_click_frame(audit_frame, audit, output_dir / "before_annotated.png")
        command = InputCommand(
            "click",
            (float(before_details["element"]["global_bbox"][0]) + float(before_details["element"]["global_bbox"][2])) / 2,
            (float(before_details["element"]["global_bbox"][1]) + float(before_details["element"]["global_bbox"][3])) / 2,
        )
        input_result = adapter.execute(command)
        report["total_inputs"] = 1
        report["input"] = {
            "backend": type(adapter.backend).__name__,
            "action": "OPEN_BUILD_MENU",
            "target": before_details["element"],
            "click_audit": audit,
            "input_result": input_result,
            "input_sent": True,
        }

        observations: list[dict[str, Any]] = []
        checkpoint_start = time.monotonic()
        for offset_ms in checkpoints_ms:
            remaining = checkpoint_start + offset_ms / 1000 - time.monotonic()
            if remaining > 0:
                time.sleep(remaining)
            checkpoint_path = output_dir / f"after_{offset_ms}ms.png"
            try:
                current_info, _frame, observation, dialog, details = _roundtrip_capture_and_observe(
                    window,
                    backend,
                    perception,
                    capture,
                    checkpoint_path,
                    close_target,
                    expected_open=True,
                    phase=f"open_only_after_{offset_ms}ms",
                    enforce_state=False,
                    require_target=False,
                )
                current_pid = backend.window_process_id(current_info.hwnd)
                if current_info.hwnd != info.hwnd or current_pid != expected_pid:
                    raise WindowError(f"window identity changed at {offset_ms}ms")
                element = _roundtrip_element(observation, close_target, expected_role="BUILD_MENU_CLOSE")
                observations.append({
                    "offset_ms": offset_ms,
                    "build_menu_open": observation.get("build_menu_open"),
                    "state_match": observation.get("build_menu_open") is True,
                    "capture": details["capture"],
                    "foreground": details["foreground"],
                    "vision": _preflight_observation_summary(observation),
                    "dialog": _preflight_observation_summary(dialog),
                    "element": element,
                    "screenshot": str(checkpoint_path),
                })
            except (WindowError, CaptureError) as exc:
                raise E2EPreflightError(f"open-only verification failed at {offset_ms}ms: {exc}") from exc
            except E2EPreflightError as exc:
                observations.append({"offset_ms": offset_ms, "state_match": False, "error": str(exc), "screenshot": str(checkpoint_path)})
        report["observations"] = observations
        report["post_click_verification"] = {
            "checkpoints_ms": list(checkpoints_ms),
            "observations": observations,
        }
        report["result"] = "PASS" if any(item.get("state_match") and not item.get("dialog", {}).get("dialog_open", False) for item in observations) else "FAIL"
        if report["result"] != "PASS":
            report["failure_class"] = "OPEN_ACTION_NOT_VERIFIED"
            report["failure_reason"] = "build_menu_open was not observed at any checkpoint"
    except Exception as exc:  # noqa: BLE001 — one-click path fails closed
        report["failure_class"] = type(exc).__name__
        report["failure_reason"] = str(exc)
        report["result"] = "FAIL"
    finally:
        store.set_runtime("live_armed", False)
        report["arm_live"] = False
        report["input_sent"] = report["total_inputs"] > 0
        (output_dir / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def run_live_build_menu_close_only(
    settings: Settings,
    store: SQLiteStore,
    *,
    output_dir: Path = Path("data/e2e/build_menu_close_only"),
    window_title: str | None = None,
    verify_timeout_seconds: float = 5.0,
    poll_seconds: float = 0.25,
    wait_for_game_foreground: bool = False,
    foreground_timeout_seconds: float = 30.0,
    checkpoints_ms: tuple[int, ...] = (200, 500, 1000, 2000),
) -> dict[str, Any]:
    """Run one guarded close-only click and never issue an open or placement input."""
    if settings.execution_mode != "live" or not settings.allow_live_input:
        raise E2EConfigurationError("close-only live diagnostic requires live mode and GOVERNOR_ALLOW_LIVE_INPUT=true")
    if not store.get_runtime("live_armed", False):
        raise E2EConfigurationError("close-only live diagnostic requires explicit live arming")
    if verify_timeout_seconds <= 0 or poll_seconds <= 0 or not checkpoints_ms:
        raise E2EConfigurationError("close-only verification timings must be positive")
    output_dir.mkdir(parents=True, exist_ok=True)
    calibration_path = output_dir.parent / "build_menu_calibration.json"
    if not calibration_path.exists():
        raise E2EConfigurationError("build_menu_calibration.json is missing")
    try:
        calibration = json.loads(calibration_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise E2EConfigurationError("build_menu_calibration.json is invalid") from exc
    calibrated_runtime_regions(calibration)
    open_target = calibration.get("open")
    close_target = calibration.get("close")
    if not isinstance(open_target, dict) or not isinstance(close_target, dict):
        raise E2EConfigurationError("calibration does not contain open and close targets")

    report: dict[str, Any] = {
        "scenario": "build_menu_close_only",
        "max_clicks": 1,
        "retry_input": False,
        "open_action": {"enabled": False, "input_sent": False},
        "placement_action": {"enabled": False, "input_sent": False},
        "keyboard_input": False,
        "total_inputs": 0,
        "unexpected_inputs": 0,
        "result": "FAIL",
    }

    try:
        backend = Win32WindowBackend()
        window = _locate_game_window(settings, backend, window_title)
        capture = ClientAreaCapture(window, WindowsGraphicsCaptureBackend(), reject_near_black=True)
        api_base, api_key, vision_model = _qwen_runtime_config(settings)
        client = QwenClient(
            api_base,
            api_key,
            vision_model,
            usage_callback=store.record_token_usage,
        )
        perception = PerceptionEngine(client, RegionCatalog(), model=vision_model)
        if wait_for_game_foreground:
            info = window.wait_for_foreground(
                timeout_seconds=foreground_timeout_seconds,
                stable_seconds=3.0,
                poll_seconds=0.5,
            )
        else:
            info = window.locate()
        expected_pid = backend.window_process_id(info.hwnd)
        if expected_pid is None:
            raise E2EPreflightError("game PID is unavailable")
        report["game"] = {
            "hwnd": info.hwnd,
            "pid": expected_pid,
            "resolution": [info.client_width, info.client_height],
        }
        adapter = WindowsSendInputAdapter(
            window,
            Win32SendInputBackend(),
            enabled=True,
            allow_clicks=True,
            allow_keyboard=False,
            expected_pid=expected_pid,
        )

        deadline = time.monotonic() + verify_timeout_seconds
        close_runtime_target = close_target
        close_target_fallback_used = False
        while True:
            try:
                before_info, before_frame, before_observation, before_dialog, before_details = _roundtrip_capture_and_observe(
                    window,
                    backend,
                    perception,
                    capture,
                    output_dir / "before.png",
                    close_runtime_target,
                    expected_open=True,
                    phase="close_only_before",
                )
                if before_info.hwnd != info.hwnd or backend.window_process_id(before_info.hwnd) != expected_pid:
                    raise WindowError("window identity changed before close-only input")
                break
            except E2EPreflightError as exc:
                if (
                    ("calibrated target not resolved" in str(exc) or "state precondition mismatch" in str(exc))
                    and not close_target_fallback_used
                    and close_runtime_target is close_target
                    and close_target.get("region") == "build_controls"
                ):
                    close_runtime_target = _close_only_runtime_target_candidates(close_target)[-1]
                    close_target_fallback_used = True
                    continue
                if "state precondition mismatch" not in str(exc) and "calibrated target not resolved" not in str(exc):
                    raise
                if time.monotonic() >= deadline:
                    raise E2EPreflightError(f"close-only precondition failed: {exc}") from exc
                time.sleep(poll_seconds)
        report["precondition"] = {
            "build_menu_open": True,
            "capture": before_details["capture"],
            "foreground": before_details["foreground"],
            "vision": _preflight_observation_summary(before_observation),
            "dialog": _preflight_observation_summary(before_dialog),
            "element": before_details["element"],
        }
        report["target_resolution"] = {
            "calibrated_region": close_target.get("region"),
            "runtime_region": close_runtime_target.get("region"),
            "fallback_used": close_target_fallback_used,
            "source": "current_frame_vision",
        }
        input_info = _roundtrip_pid_guard(window, backend, info.hwnd, expected_pid, "close-only input")
        audit_frame = capture.capture()
        diagnostic = audit_frame.diagnostic.to_dict() if audit_frame.diagnostic else {}
        if diagnostic.get("near_black_frame"):
            raise E2EPreflightError("CAPTURE_BLACK_FRAME before close-only input")
        audit = _roundtrip_click_audit(input_info, backend, before_details["element"], close_runtime_target)
        audit["source_screenshot"] = str(output_dir / "before_click_source.png")
        audit["annotated_screenshot"] = str(output_dir / "before_annotated.png")
        (output_dir / "before_click_source.png").write_bytes(audit_frame.png)
        _annotate_click_frame(audit_frame, audit, output_dir / "before_annotated.png")
        command = InputCommand(
            "click",
            (float(before_details["element"]["global_bbox"][0]) + float(before_details["element"]["global_bbox"][2])) / 2,
            (float(before_details["element"]["global_bbox"][1]) + float(before_details["element"]["global_bbox"][3])) / 2,
        )
        input_result = adapter.execute(command)
        report["total_inputs"] = 1
        report["input"] = {
            "backend": type(adapter.backend).__name__,
            "action": "CLOSE_BUILD_MENU",
            "target": before_details["element"],
            "click_audit": audit,
            "input_result": input_result,
            "input_sent": True,
        }

        observations: list[dict[str, Any]] = []
        checkpoint_start = time.monotonic()
        for offset_ms in checkpoints_ms:
            remaining = checkpoint_start + offset_ms / 1000 - time.monotonic()
            if remaining > 0:
                time.sleep(remaining)
            checkpoint_path = output_dir / f"after_{offset_ms}ms.png"
            try:
                current_info, _frame, observation, dialog, details = _roundtrip_capture_and_observe(
                    window,
                    backend,
                    perception,
                    capture,
                    checkpoint_path,
                    open_target,
                    expected_open=False,
                    phase=f"close_only_after_{offset_ms}ms",
                    enforce_state=False,
                    require_target=False,
                )
                current_pid = backend.window_process_id(current_info.hwnd)
                if current_info.hwnd != info.hwnd or current_pid != expected_pid:
                    raise WindowError(f"window identity changed at {offset_ms}ms")
                element = _roundtrip_element(observation, open_target, expected_role="BUILD_MENU_OPEN")
                observations.append({
                    "offset_ms": offset_ms,
                    "build_menu_open": observation.get("build_menu_open"),
                    "state_match": observation.get("build_menu_open") is False,
                    "capture": details["capture"],
                    "foreground": details["foreground"],
                    "vision": _preflight_observation_summary(observation),
                    "dialog": _preflight_observation_summary(dialog),
                    "element": element,
                    "screenshot": str(checkpoint_path),
                })
            except (WindowError, CaptureError) as exc:
                raise E2EPreflightError(f"close-only verification failed at {offset_ms}ms: {exc}") from exc
            except E2EPreflightError as exc:
                observations.append({"offset_ms": offset_ms, "state_match": False, "error": str(exc), "screenshot": str(checkpoint_path)})
        report["observations"] = observations
        report["post_click_verification"] = {
            "checkpoints_ms": list(checkpoints_ms),
            "observations": observations,
        }
        report["result"] = "PASS" if any(item.get("state_match") and not item.get("dialog", {}).get("dialog_open", False) for item in observations) else "FAIL"
        if report["result"] != "PASS":
            report["failure_class"] = "CLOSE_ACTION_NOT_VERIFIED"
            report["failure_reason"] = "build_menu_open remained true at every checkpoint"
    except Exception as exc:  # noqa: BLE001 — one-click path fails closed
        report["failure_class"] = type(exc).__name__
        report["failure_reason"] = str(exc)
        report["result"] = "FAIL"
    finally:
        store.set_runtime("live_armed", False)
        report["arm_live"] = False
        report["input_sent"] = report["total_inputs"] > 0
        (output_dir / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


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
    api_base, api_key, vision_model = _qwen_runtime_config(settings)

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

    client = QwenClient(
        api_base,
        api_key,
        vision_model,
        usage_callback=store.record_token_usage,
    )
    perception = PerceptionEngine(client, RegionCatalog(), model=vision_model)
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
