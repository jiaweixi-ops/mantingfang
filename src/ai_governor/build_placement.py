"""Read-only placement-state and cancel-control evidence for V2.4E0.

This module never sends input and never turns a map ghost into an actionable
target.  It compares a fresh post-selection frame with the fresh
``CATEGORY_OPEN`` baseline and only emits a cancel target when it is newly
visible in the current frame.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Iterable, Mapping

from .build_menu import BuildMenuSnapshot, BuildMenuState, FrameGeometry, parse_build_menu_snapshot
from .build_option_detector import detect_build_option_slots
from .perception import RegionCatalog


MIN_PLACEMENT_CONFIDENCE = 0.90


@dataclass(frozen=True)
class PlacementEvidence:
    placement_mode: bool
    confidence: float
    evidence: tuple[str, ...]
    cancel_target: dict[str, Any] | None
    map_delta_score: float
    baseline_options: int
    current_options: int

    @property
    def evidence_count(self) -> int:
        return len(self.evidence)

    def to_dict(self) -> dict[str, Any]:
        return {
            "placement_mode": self.placement_mode,
            "confidence": self.confidence,
            "evidence": list(self.evidence),
            "evidence_count": self.evidence_count,
            "cancel_target": self.cancel_target,
            "map_delta_score": self.map_delta_score,
            "baseline_options": self.baseline_options,
            "current_options": self.current_options,
        }


def _is_red(r: int, g: int, b: int) -> bool:
    return r >= 130 and r > g * 1.30 and r > b * 1.20 and (r - min(g, b)) >= 55


def _components(mask: list[bool], width: int, height: int) -> Iterable[tuple[int, int, int, int, int]]:
    seen = bytearray(len(mask))
    for start, active in enumerate(mask):
        if not active or seen[start]:
            continue
        stack = [start]
        seen[start] = 1
        points: list[tuple[int, int]] = []
        while stack:
            current = stack.pop()
            x, y = current % width, current // width
            points.append((x, y))
            for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if 0 <= nx < width and 0 <= ny < height:
                    neighbor = ny * width + nx
                    if mask[neighbor] and not seen[neighbor]:
                        seen[neighbor] = 1
                        stack.append(neighbor)
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        yield min(xs), min(ys), max(xs) + 1, max(ys) + 1, len(points)


def bbox_iou(first: list[float] | tuple[float, ...], second: list[float] | tuple[float, ...]) -> float:
    left = max(first[0], second[0])
    top = max(first[1], second[1])
    right = min(first[2], second[2])
    bottom = min(first[3], second[3])
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    first_area = max(0.0, first[2] - first[0]) * max(0.0, first[3] - first[1])
    second_area = max(0.0, second[2] - second[0]) * max(0.0, second[3] - second[1])
    union = first_area + second_area - intersection
    return intersection / union if union else 0.0


def detect_current_frame_cancel_controls(
    rgba: bytes,
    width: int,
    height: int,
    region_catalog: RegionCatalog,
    *,
    excluded_bboxes: Iterable[list[float] | tuple[float, ...]] = (),
) -> list[dict[str, Any]]:
    """Find red cancel-like controls in the formal current-frame controls ROI."""
    if width <= 0 or height <= 0 or len(rgba) != width * height * 4:
        return []
    left, top, right, bottom = region_catalog.get("build_controls").crop_box(width, height)
    mask = [False] * (width * height)
    for y in range(top, bottom):
        for x in range(left, right):
            offset = (y * width + x) * 4
            mask[y * width + x] = _is_red(rgba[offset], rgba[offset + 1], rgba[offset + 2])
    targets: list[dict[str, Any]] = []
    for box_left, box_top, box_right, box_bottom, pixels in _components(mask, width, height):
        box_width, box_height = box_right - box_left, box_bottom - box_top
        if pixels < 18 or not (8 <= box_width <= 180 and 8 <= box_height <= 180):
            continue
        if not 0.35 <= box_width / box_height <= 3.2:
            continue
        bbox = [box_left / width, box_top / height, box_right / width, box_bottom / height]
        if any(bbox_iou(bbox, list(previous)) >= 0.45 for previous in excluded_bboxes):
            continue
        density = pixels / float(box_width * box_height)
        confidence = min(0.99, max(MIN_PLACEMENT_CONFIDENCE, 0.90 + min(0.08, density * 0.30)))
        targets.append({
            "id": "build_placement_cancel",
            "canonical_id": "build_placement_cancel",
            "raw_id": "local_red_placement_cancel",
            "role": "BUILD_PLACEMENT_CANCEL",
            "label": "unknown",
            "bbox": bbox,
            "global_bbox": list(bbox),
            "confidence": confidence,
            "source": "deterministic_current_frame_placement_cancel",
            "region": "build_controls",
        })
    return sorted(targets, key=lambda item: (-item["confidence"], item["bbox"][1], item["bbox"][0]))


def _sample_delta(
    baseline: bytes,
    current: bytes,
    width: int,
    height: int,
    region: tuple[float, float, float, float],
) -> float:
    left, top, right, bottom = (
        round(region[0] * width), round(region[1] * height),
        round(region[2] * width), round(region[3] * height),
    )
    total = 0
    count = 0
    for y in range(top, max(top + 1, bottom), max(1, (bottom - top) // 24)):
        for x in range(left, max(left + 1, right), max(1, (right - left) // 32)):
            offset = (y * width + x) * 4
            total += sum(abs(baseline[offset + channel] - current[offset + channel]) for channel in range(3))
            count += 3
    return total / (count * 255.0) if count else 0.0


def analyze_placement_transition(
    baseline_rgba: bytes,
    current_rgba: bytes,
    width: int,
    height: int,
    baseline_snapshot: BuildMenuSnapshot,
    current_snapshot: BuildMenuSnapshot,
    region_catalog: RegionCatalog,
) -> PlacementEvidence:
    """Fuse independent current-frame signals; fail closed with fewer than two."""
    baseline_cancel = detect_current_frame_cancel_controls(
        baseline_rgba, width, height, region_catalog
    )
    baseline_cancel_boxes = [item["bbox"] for item in baseline_cancel]
    current_cancel = detect_current_frame_cancel_controls(
        current_rgba, width, height, region_catalog, excluded_bboxes=baseline_cancel_boxes
    )
    baseline_options = len(baseline_snapshot.options)
    current_options = len(detect_build_option_slots(current_rgba, width, height, region_catalog))
    controls_changed = baseline_options > 0 and current_options < baseline_options
    map_delta = _sample_delta(baseline_rgba, current_rgba, width, height, (0.18, 0.12, 0.82, 0.90))
    evidence: list[str] = []
    cancel_target = current_cancel[0] if current_cancel else None
    if cancel_target is not None:
        evidence.append("new_current_frame_cancel_control")
    if controls_changed:
        evidence.append("category_options_transitioned")
    if map_delta >= 0.08:
        evidence.append("map_placement_visual_delta")
    confidence = min(0.99, 0.90 + min(0.08, map_delta * 0.25)) if len(evidence) >= 2 else 0.0
    return PlacementEvidence(
        placement_mode=len(evidence) >= 2 and cancel_target is not None,
        confidence=confidence,
        evidence=tuple(evidence),
        cancel_target=cancel_target,
        map_delta_score=map_delta,
        baseline_options=baseline_options,
        current_options=current_options,
    )


def placement_snapshot(
    evidence: PlacementEvidence,
    *,
    geometry: FrameGeometry,
    frame_id: str,
) -> BuildMenuSnapshot:
    """Build a strict snapshot whose placement state is evidence-bound."""
    elements = [evidence.cancel_target] if evidence.cancel_target else []
    observation = {
        "build_menu_open": False,
        "current_screen": "建筑放置",
        "ui_elements": elements,
        "placement_mode": evidence.placement_mode,
        "building_selected": evidence.placement_mode,
        "placement_confidence": evidence.confidence,
        "placement_evidence_count": evidence.evidence_count,
        "placement_evidence": list(evidence.evidence),
    }
    snapshot = parse_build_menu_snapshot(observation, geometry=geometry)
    return replace(snapshot, evidence={**snapshot.evidence, "frame_id": frame_id, **evidence.to_dict()})


def validate_fresh_cancel_target(
    target: Mapping[str, Any] | None,
    *,
    frame_id: str,
    geometry: FrameGeometry,
    current_frame_id: str,
) -> None:
    """Reject stale cancel identity, geometry, or low-confidence targets."""
    if not isinstance(target, dict):
        raise ValueError("missing current-frame placement cancel target")
    if target.get("role") != "BUILD_PLACEMENT_CANCEL":
        raise ValueError("target is not BUILD_PLACEMENT_CANCEL")
    if target.get("frame_id", current_frame_id) != current_frame_id or frame_id != current_frame_id:
        raise ValueError("stale placement cancel frame")
    if float(target.get("confidence", 0.0)) < MIN_PLACEMENT_CONFIDENCE:
        raise ValueError("placement cancel confidence is below threshold")
    bbox = target.get("global_bbox", target.get("bbox"))
    if not isinstance(bbox, list) or len(bbox) != 4 or not 0.0 <= bbox[0] < bbox[2] <= 1.0 or not 0.0 <= bbox[1] < bbox[3] <= 1.0:
        raise ValueError("placement cancel bbox is outside current client bounds")
    target_geometry = target.get("geometry")
    if target_geometry is not None and target_geometry != geometry.to_dict():
        raise ValueError("placement cancel geometry is stale")
