"""Fresh-frame, read-only adapter for real-game Build Menu calibration.

The pure schema and state rules live in :mod:`build_menu`.  This adapter is
the only layer that knows about WGC and Vision.  It performs one Vision
calibration request per phase, then tracks the resolved UI patches locally in
fresh frames so that calibration does not become a per-frame model loop.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from .build_menu import (
    BuildMenuSchemaError,
    BuildMenuSnapshot,
    BuildMenuState,
    FrameGeometry,
    parse_build_menu_snapshot,
)
from .build_option_detector import detect_build_option_slots
from .capture import CaptureBlackFrameError, ClientAreaCapture, WindowsGraphicsCaptureBackend
from .config import Settings
from .models import utc_now
from .perception import PerceptionEngine, RegionCatalog
from .qwen import QwenClient, QwenConfigurationError
from .storage import SQLiteStore
from .window import SteamWindowAdapter, Win32WindowBackend, WindowError, WindowNotFound


class BuildMenuCalibrationError(RuntimeError):
    """Raised when a read-only phase cannot produce safe current-frame evidence."""


_PHASE_CONFIG = {
    "closed": {
        "output_key": "closed",
        "region": "build_entry",
        "expected_state": BuildMenuState.CLOSED,
        "context": "当前建筑菜单应保持关闭。只识别 BUILD_MENU_OPEN 或 BUILD_MENU_TOGGLE 控件，不执行任何操作。",
        "required_roles": {"BUILD_MENU_OPEN", "BUILD_MENU_TOGGLE"},
    },
    "root": {
        "output_key": "root_open",
        "region": "build_controls",
        "expected_state": BuildMenuState.ROOT_OPEN,
        "context": "用户已经手动打开建筑菜单。只识别真实 BUILD_CATEGORY_TAB 分类，不执行任何操作。",
        "required_roles": {"BUILD_MENU_CLOSE", "BUILD_MENU_TOGGLE", "BUILD_CATEGORY_TAB"},
    },
    "category": {
        "output_key": "category_open",
        "region": "build_controls",
        "expected_state": BuildMenuState.CATEGORY_OPEN,
        "context": "用户已经手动进入一个普通建筑分类。只识别真实 BUILD_OPTION/BUILD_DISABLED_OPTION 建筑卡片，不执行任何操作。未知 label/locked/costs 必须留空或 UNKNOWN，不要猜测。",
        "required_roles": {"BUILD_MENU_CLOSE", "BUILD_MENU_TOGGLE", "BUILD_OPTION", "BUILD_DISABLED_OPTION"},
    },
}


def _pixel_bounds(bbox: tuple[float, float, float, float], width: int, height: int) -> tuple[int, int, int, int]:
    left, top, right, bottom = bbox
    return (
        max(0, min(width - 1, round(left * width))),
        max(0, min(height - 1, round(top * height))),
        max(1, min(width, round(right * width))),
        max(1, min(height, round(bottom * height))),
    )


def _patch_error(
    reference: bytes,
    current: bytes,
    width: int,
    height: int,
    reference_box: tuple[int, int, int, int],
    current_box: tuple[int, int, int, int],
) -> float:
    ref_left, ref_top, ref_right, ref_bottom = reference_box
    cur_left, cur_top, cur_right, cur_bottom = current_box
    ref_width, ref_height = ref_right - ref_left, ref_bottom - ref_top
    cur_width, cur_height = cur_right - cur_left, cur_bottom - cur_top
    if ref_width <= 0 or ref_height <= 0 or ref_width != cur_width or ref_height != cur_height:
        return 1.0
    step = max(1, min(ref_width, ref_height) // 16)
    total = 0
    count = 0
    for y in range(0, ref_height, step):
        for x in range(0, ref_width, step):
            ref_offset = ((ref_top + y) * width + ref_left + x) * 4
            cur_offset = ((cur_top + y) * width + cur_left + x) * 4
            for channel in range(3):
                total += abs(reference[ref_offset + channel] - current[cur_offset + channel])
                count += 1
    return total / (count * 255.0) if count else 1.0


def _track_bbox(
    reference_rgba: bytes,
    current_rgba: bytes,
    width: int,
    height: int,
    bbox: list[float] | tuple[float, float, float, float],
    *,
    search_radius: int = 24,
) -> tuple[list[float] | None, float]:
    """Find the same UI patch in this fresh frame; never returns a prior bbox blindly."""
    try:
        normalized = tuple(float(value) for value in bbox)
    except (TypeError, ValueError):
        return None, 0.0
    reference_box = _pixel_bounds(normalized, width, height)
    left, top, right, bottom = reference_box
    patch_width, patch_height = right - left, bottom - top
    if patch_width <= 1 or patch_height <= 1:
        return None, 0.0
    best_error = 1.0
    best_box: tuple[int, int, int, int] | None = None
    for delta_y in range(-search_radius, search_radius + 1):
        for delta_x in range(-search_radius, search_radius + 1):
            candidate_left = left + delta_x
            candidate_top = top + delta_y
            candidate_box = (
                candidate_left,
                candidate_top,
                candidate_left + patch_width,
                candidate_top + patch_height,
            )
            if candidate_left < 0 or candidate_top < 0 or candidate_box[2] > width or candidate_box[3] > height:
                continue
            error = _patch_error(reference_rgba, current_rgba, width, height, reference_box, candidate_box)
            if error < best_error:
                best_error, best_box = error, candidate_box
    if best_box is None:
        return None, 0.0
    return [
        best_box[0] / width,
        best_box[1] / height,
        best_box[2] / width,
        best_box[3] / height,
    ], max(0.0, 1.0 - best_error)


def _resolve_local_menu_control(
    rgba: bytes,
    width: int,
    height: int,
    catalog: RegionCatalog,
) -> dict[str, Any] | None:
    """Resolve the visible red close/toggle control from the current frame.

    Song's open-menu close control is in the existing ``build_entry`` formal
    ROI, not in the lower ``build_controls`` crop.  This resolver uses only
    current-frame pixels and that catalog boundary; it never consumes or
    returns a calibration bbox as an actionable target.
    """
    region = catalog.get("build_entry")
    left, top, right, bottom = region.crop_box(width, height)
    search_left = max(left, int(width * 0.88))
    search_top = max(top, int(height * 0.08))
    search_bottom = min(bottom, int(height * 0.25))
    if search_left >= right or search_top >= search_bottom:
        return None
    visited: set[tuple[int, int]] = set()
    components: list[tuple[int, int, int, int, int]] = []

    def is_red(x: int, y: int) -> bool:
        offset = (y * width + x) * 4
        red, green, blue = rgba[offset:offset + 3]
        return red >= 140 and red > green * 1.45 and red > blue * 1.35 and green <= 150

    for y in range(search_top, search_bottom):
        for x in range(search_left, right):
            if (x, y) in visited or not is_red(x, y):
                continue
            stack = [(x, y)]
            visited.add((x, y))
            pixels: list[tuple[int, int]] = []
            while stack:
                current_x, current_y = stack.pop()
                pixels.append((current_x, current_y))
                for next_x, next_y in (
                    (current_x - 1, current_y),
                    (current_x + 1, current_y),
                    (current_x, current_y - 1),
                    (current_x, current_y + 1),
                ):
                    if (
                        search_left <= next_x < right
                        and search_top <= next_y < search_bottom
                        and (next_x, next_y) not in visited
                        and is_red(next_x, next_y)
                    ):
                        visited.add((next_x, next_y))
                        stack.append((next_x, next_y))
            if len(pixels) >= 40:
                xs = [item[0] for item in pixels]
                ys = [item[1] for item in pixels]
                components.append((len(pixels), min(xs), min(ys), max(xs) + 1, max(ys) + 1))
    if not components:
        return None
    area, box_left, box_top, box_right, box_bottom = max(components)
    box_width = box_right - box_left
    box_height = box_bottom - box_top
    if box_width < 8 or box_height < 8:
        return None
    fill = area / float(box_width * box_height)
    squareness = 1.0 - min(1.0, abs(box_width - box_height) / max(box_width, box_height))
    confidence = min(0.99, max(0.90, 0.90 + 0.04 * min(1.0, fill) + 0.05 * squareness))
    bbox = [box_left / width, box_top / height, box_right / width, box_bottom / height]
    return {
        "id": "build_menu_close_control",
        "canonical_id": "build_menu_close_control",
        "raw_id": "local_red_close_control",
        "role": "BUILD_MENU_CLOSE",
        "label": "关闭",
        "bbox": bbox,
        "global_bbox": bbox,
        "confidence": confidence,
        "region": "build_entry",
        "resolver": "deterministic_current_frame_red_control",
    }


def _geometry_key(geometry: FrameGeometry) -> tuple[Any, ...]:
    return (
        geometry.hwnd,
        geometry.pid,
        geometry.client_width,
        geometry.client_height,
        geometry.client_origin,
        geometry.dpi,
    )


def _reusable_root_categories(output_dir: Path, geometry: FrameGeometry) -> dict[str, Any] | None:
    """Load prior categories only as a non-actionable seed when identity matches."""
    path = output_dir / "root_open" / "result.json"
    try:
        previous = json.loads(path.read_text(encoding="utf-8"))
        sample = previous["samples"][0]
        previous_geometry = sample["geometry"]
        previous_key = (
            int(previous_geometry["hwnd"]),
            int(previous_geometry["pid"]),
            int(previous_geometry["client_width"]),
            int(previous_geometry["client_height"]),
            tuple(int(value) for value in previous_geometry["client_origin"]),
            int(previous_geometry["dpi"]),
        )
        if previous_key != _geometry_key(geometry):
            return None
        categories = sample["snapshot"]["categories"]
        if not isinstance(categories, list) or not categories:
            return None
        elements: list[dict[str, Any]] = []
        for item in categories:
            if not isinstance(item, dict):
                return None
            bbox = item.get("global_bbox")
            if not isinstance(bbox, list) or len(bbox) != 4:
                return None
            elements.append({
                "id": item.get("id"),
                "canonical_id": item.get("id"),
                "raw_id": item.get("id"),
                "role": "BUILD_CATEGORY_TAB",
                "label": item.get("label") or "category",
                "bbox": list(bbox),
                "global_bbox": list(bbox),
                "confidence": float(item.get("confidence", 0.0)),
            })
        return {"categories": elements, "ui_elements": elements}
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _compose_phase_observation(
    phase: str,
    base: Mapping[str, Any],
    local_control: dict[str, Any] | None,
) -> dict[str, Any]:
    elements = [dict(item) for item in base.get("ui_elements", []) if isinstance(item, Mapping)]
    if local_control is not None:
        elements.append(dict(local_control))
    observation: dict[str, Any] = {
        **dict(base),
        "build_menu_open": True,
        "current_screen": "建筑菜单",
        "ui_elements": elements,
    }
    if phase == "root":
        categories = [item for item in elements if item.get("role") == "BUILD_CATEGORY_TAB"]
        observation["categories"] = categories
        observation.pop("building_options", None)
    elif phase == "category":
        options = [item for item in elements if item.get("role") in {"BUILD_OPTION", "BUILD_DISABLED_OPTION"}]
        observation["building_options"] = options
        observation.pop("categories", None)
    return observation


def _geometry(capture: ClientAreaCapture, backend: Win32WindowBackend) -> FrameGeometry:
    info = capture.last_info
    if info is None:
        raise BuildMenuCalibrationError("capture did not expose current window geometry")
    pid = backend.window_process_id(info.hwnd)
    if pid is None:
        raise BuildMenuCalibrationError("current Song HWND has no readable PID")
    return FrameGeometry(
        hwnd=info.hwnd,
        pid=pid,
        client_width=info.client_width,
        client_height=info.client_height,
        client_origin=(info.screen_left, info.screen_top),
        dpi=backend.window_dpi(info.hwnd),
        captured_at=utc_now(),
    )


def _tracked_observation(
    reference: Mapping[str, Any],
    reference_rgba: bytes,
    current_rgba: bytes,
    width: int,
    height: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    tracked: list[dict[str, Any]] = []
    matches: list[dict[str, Any]] = []
    for raw in reference.get("ui_elements", []):
        if not isinstance(raw, Mapping):
            continue
        bbox = raw.get("global_bbox", raw.get("bbox"))
        current_bbox, match_confidence = _track_bbox(reference_rgba, current_rgba, width, height, bbox)
        if current_bbox is None:
            matches.append({"id": raw.get("id"), "matched": False, "confidence": 0.0})
            continue
        reference_confidence = raw.get("confidence")
        confidence = min(float(reference_confidence), match_confidence) if isinstance(reference_confidence, (int, float)) else match_confidence
        tracked.append({
            **raw,
            "bbox": current_bbox,
            "global_bbox": current_bbox,
            "confidence": confidence,
        })
        matches.append({
            "id": raw.get("id"),
            "canonical_id": raw.get("canonical_id", raw.get("id")),
            "matched": True,
            "bbox": current_bbox,
            "confidence": confidence,
        })
    observation = {key: value for key, value in reference.items() if key != "ui_elements"}
    observation["ui_elements"] = tracked
    return observation, matches


def _bbox_iou(first: Any, second: Any) -> float:
    if not isinstance(first, (list, tuple)) or not isinstance(second, (list, tuple)) or len(first) != 4 or len(second) != 4:
        return 0.0
    try:
        left = max(float(first[0]), float(second[0]))
        top = max(float(first[1]), float(second[1]))
        right = min(float(first[2]), float(second[2]))
        bottom = min(float(first[3]), float(second[3]))
        first_area = max(0.0, float(first[2]) - float(first[0])) * max(0.0, float(first[3]) - float(first[1]))
        second_area = max(0.0, float(second[2]) - float(second[0])) * max(0.0, float(second[3]) - float(second[1]))
    except (TypeError, ValueError):
        return 0.0
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    union = first_area + second_area - intersection
    return intersection / union if union else 0.0


def _center_drift_pixels(first: Any, second: Any, geometry: FrameGeometry) -> float:
    if not isinstance(first, (list, tuple)) or not isinstance(second, (list, tuple)) or len(first) != 4 or len(second) != 4:
        return float("inf")
    try:
        first_x = (float(first[0]) + float(first[2])) / 2 * geometry.client_width
        first_y = (float(first[1]) + float(first[3])) / 2 * geometry.client_height
        second_x = (float(second[0]) + float(second[2])) / 2 * geometry.client_width
        second_y = (float(second[1]) + float(second[3])) / 2 * geometry.client_height
    except (TypeError, ValueError):
        return float("inf")
    return ((first_x - second_x) ** 2 + (first_y - second_y) ** 2) ** 0.5


def _required_elements(snapshot: BuildMenuSnapshot, phase: str) -> list[tuple[str, Any]]:
    elements: list[tuple[str, Any]] = []
    if phase == "closed":
        if snapshot.open_control is not None:
            elements.append((snapshot.open_control.get("canonical_id", "open_control"), snapshot.open_control))
    elif phase == "root":
        if snapshot.close_control is not None:
            elements.append((snapshot.close_control.get("canonical_id", "close_control"), snapshot.close_control))
        elements.extend((item.id, item) for item in snapshot.categories)
    elif phase == "category":
        if snapshot.close_control is not None:
            elements.append((snapshot.close_control.get("canonical_id", "close_control"), snapshot.close_control))
        elements.extend((item.id, item) for item in snapshot.options)
    return elements


def assess_phase_snapshots(phase: str, snapshots: list[BuildMenuSnapshot], *, iou_threshold: float = 0.85) -> dict[str, Any]:
    """Return bounded stability evidence for three fresh, read-only samples."""
    if phase not in _PHASE_CONFIG:
        raise BuildMenuCalibrationError(f"unknown calibration phase: {phase}")
    expected = _PHASE_CONFIG[phase]["expected_state"]
    states = [snapshot.state for snapshot in snapshots]
    stable = len(snapshots) == 3 and all(state is expected for state in states)
    geometry_keys = [
        (
            snapshot.geometry.hwnd,
            snapshot.geometry.pid,
            snapshot.geometry.client_width,
            snapshot.geometry.client_height,
            snapshot.geometry.client_origin,
            snapshot.geometry.dpi,
        )
        for snapshot in snapshots
        if snapshot.geometry is not None
    ]
    stable = stable and len(geometry_keys) == len(snapshots) and len(set(geometry_keys)) == 1
    required_counts = {
        "categories_found": min((len(snapshot.categories) for snapshot in snapshots), default=0),
        "options_found": min((len(snapshot.options) for snapshot in snapshots), default=0),
    }
    if phase == "root":
        stable = stable and required_counts["categories_found"] >= 1
    if phase == "category":
        stable = stable and required_counts["options_found"] >= 1
    center_drift_threshold = 0.0
    if phase == "category" and snapshots and snapshots[0].geometry is not None:
        center_drift_threshold = max(4.0, min(snapshots[0].geometry.client_width, snapshots[0].geometry.client_height) * 0.005)
    if snapshots:
        first_items = _required_elements(snapshots[0], phase)
        for label, first in first_items:
            for snapshot in snapshots[1:]:
                current_items = dict(_required_elements(snapshot, phase))
                if hasattr(first, "id"):
                    current = current_items.get(first.id)
                    first_bbox = first.global_bbox or first.bbox
                    current_bbox = current.global_bbox or current.bbox if current is not None else None
                    current_confidence = current.confidence if current is not None else 0.0
                else:
                    identifier = first.get("canonical_id", first.get("id")) if isinstance(first, Mapping) else None
                    current = current_items.get(identifier)
                    first_bbox = first.get("global_bbox", first.get("bbox")) if isinstance(first, Mapping) else None
                    current_bbox = current.get("global_bbox", current.get("bbox")) if isinstance(current, Mapping) else None
                    current_confidence = current.get("confidence", 0.0) if isinstance(current, Mapping) else 0.0
                if (
                    current is None
                    or current_confidence < MIN_CALIBRATION_CONFIDENCE
                    or _bbox_iou(first_bbox, current_bbox) < iou_threshold
                    or (phase == "category" and _center_drift_pixels(first_bbox, current_bbox, snapshots[0].geometry) > center_drift_threshold)
                ):
                    stable = False
    return {
        "samples": len(snapshots),
        "stable": stable,
        "states": [state.value for state in states],
        **required_counts,
        "iou_threshold": iou_threshold,
        "center_drift_threshold_px": center_drift_threshold,
        "actionable_confidence": MIN_CALIBRATION_CONFIDENCE,
    }


MIN_CALIBRATION_CONFIDENCE = 0.90


def _phase_result_path(output_dir: Path, phase: str) -> tuple[Path, Path]:
    key = _PHASE_CONFIG[phase]["output_key"]
    return output_dir / key / "result.json", output_dir / "result.json"


def sample_build_menu_phase(
    settings: Settings,
    store: SQLiteStore,
    *,
    phase: str,
    samples: int = 3,
    interval_seconds: float = 0.5,
    output_dir: Path = Path("data/probe/V2.4ABR"),
    window_title: str | None = None,
    vision_model: str = "qwen3.8-flash",
) -> dict[str, Any]:
    """Capture one manual UI phase with zero input and bounded Vision use."""
    if phase not in _PHASE_CONFIG:
        raise BuildMenuCalibrationError(f"unknown calibration phase: {phase}")
    if samples != 3:
        raise BuildMenuCalibrationError("V2.4A/B-R requires exactly three samples")
    if interval_seconds < 0:
        raise BuildMenuCalibrationError("interval_seconds must be non-negative")
    backend = Win32WindowBackend()
    title = window_title or settings.game_window_title
    window = SteamWindowAdapter(title, backend)
    try:
        window.locate()
    except WindowNotFound:
        if window_title or title == "Song":
            raise
        window = SteamWindowAdapter("Song", backend)
        window.locate()
    capture = ClientAreaCapture(window, WindowsGraphicsCaptureBackend(), reject_near_black=True)
    catalog = RegionCatalog()
    client: QwenClient | None = None
    perception: PerceptionEngine | None = None

    def ensure_perception() -> PerceptionEngine:
        nonlocal client, perception
        if perception is not None:
            return perception
        if not settings.qwen_api_key:
            raise QwenConfigurationError("QWEN_API_KEY is not configured")
        client = QwenClient(
            settings.qwen_api_base,
            settings.qwen_api_key,
            vision_model,
            usage_callback=store.record_token_usage,
        )
        perception = PerceptionEngine(client, catalog, model=vision_model)
        return perception

    region_name = _PHASE_CONFIG[phase]["region"]
    snapshots: list[BuildMenuSnapshot] = []
    sample_reports: list[dict[str, Any]] = []
    reference_observation: dict[str, Any] | None = None
    reference_rgba: bytes | None = None
    qwen_calls = 0
    for index in range(samples):
        frame = capture.capture()
        geometry = _geometry(capture, backend)
        frame_id = str(uuid4())
        if index == 0:
            if phase == "root":
                seed = _reusable_root_categories(output_dir, geometry)
                if seed is not None:
                    reference_observation = seed
                    observation, tracking = _tracked_observation(
                        seed,
                        frame.rgba,
                        frame.rgba,
                        frame.width,
                        frame.height,
                    )
                else:
                    observation = ensure_perception().observe_build_categories_rgba(
                        frame.rgba,
                        frame.width,
                        frame.height,
                        context=str(_PHASE_CONFIG[phase]["context"]),
                    ).data
                    reference_observation = dict(observation)
                    tracking = []
                    qwen_calls += 1
            elif phase == "category":
                slots = detect_build_option_slots(frame.rgba, frame.width, frame.height, catalog)
                observation = {"building_options": slots, "ui_elements": slots}
                reference_observation = dict(observation)
                tracking = []
            else:
                observation = ensure_perception().observe_rgba(
                    frame.rgba,
                    frame.width,
                    frame.height,
                    region_name,
                    context=str(_PHASE_CONFIG[phase]["context"]),
                ).data
                reference_observation = dict(observation)
                tracking = []
            reference_rgba = frame.rgba
        elif phase == "category":
            slots = detect_build_option_slots(frame.rgba, frame.width, frame.height, catalog)
            observation = {"building_options": slots, "ui_elements": slots}
            tracking = []
        else:
            if reference_observation is None or reference_rgba is None:
                raise BuildMenuCalibrationError("missing first-frame calibration reference")
            observation, tracking = _tracked_observation(
                reference_observation,
                reference_rgba,
                frame.rgba,
                frame.width,
                frame.height,
            )
        if phase in {"root", "category"}:
            observation = _compose_phase_observation(
                phase,
                observation,
                _resolve_local_menu_control(frame.rgba, frame.width, frame.height, catalog),
            )
        snapshot = parse_build_menu_snapshot(observation, geometry=geometry)
        snapshots.append(snapshot)
        sample_reports.append({
            "sample": index + 1,
            "frame_id": frame_id,
            "state": snapshot.state.value,
            "geometry": geometry.to_dict(),
            "capture": frame.diagnostic.to_dict() if frame.diagnostic else None,
            "snapshot": snapshot.to_dict(),
            "tracking": tracking,
            "actionable": False,
        })
        if index + 1 < samples and interval_seconds:
            time.sleep(interval_seconds)
    stability = assess_phase_snapshots(phase, snapshots)
    result = {
        "phase": "V2.4A/B-R",
        "phase_name": _PHASE_CONFIG[phase]["output_key"],
        "region": region_name,
        "control_resolver": "deterministic_current_frame_red_control" if phase in {"root", "category"} else "vision",
        "vision_model": vision_model,
        "qwen_calls": qwen_calls,
        "sendinput_calls": 0,
        "keyboard_input": 0,
        "mouse_input": 0,
        "map_clicks": 0,
        "save_writes": 0,
        "memory_writes": 0,
        "runtime_telemetry": False,
        "mono_debugger": False,
        "stability": stability,
        "samples": sample_reports,
    }
    phase_path, combined_path = _phase_result_path(output_dir, phase)
    phase_path.parent.mkdir(parents=True, exist_ok=True)
    phase_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    combined: dict[str, Any] = {"phase": "V2.4A/B-R", "qwen_calls": 0, "sendinput_calls": 0, "map_clicks": 0, "save_writes": 0, "memory_writes": 0}
    if combined_path.exists():
        try:
            previous = json.loads(combined_path.read_text(encoding="utf-8"))
            if isinstance(previous, dict):
                combined.update(previous)
        except (OSError, json.JSONDecodeError):
            pass
    combined["qwen_calls"] = int(combined.get("qwen_calls", 0)) + qwen_calls
    combined["sendinput_calls"] = 0
    combined["map_clicks"] = 0
    combined["save_writes"] = 0
    combined["memory_writes"] = 0
    combined[_PHASE_CONFIG[phase]["output_key"]] = stability
    combined_path.parent.mkdir(parents=True, exist_ok=True)
    combined_path.write_text(json.dumps(combined, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result
