"""Local, current-frame geometry detector for Song Build Menu option slots.

The detector deliberately recognizes only repeated visual card/slot geometry.
It does not infer a building's name, costs, availability, or category.  Its
output is therefore safe to use as read-only calibration evidence only.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .perception import RegionCatalog


_MIN_WIDTH_PX = 45
_MAX_WIDTH_RATIO = 0.16
_MIN_HEIGHT_PX = 42
_MAX_HEIGHT_RATIO = 0.22
_MERGE_GAP_PX = 18
_MIN_COMPONENT_PIXELS_PER_COLUMN = 5


def _foreground(red: int, green: int, blue: int) -> bool:
    """Return whether a pixel is structured content rather than parchment."""
    brightest = max(red, green, blue)
    darkest = min(red, green, blue)
    luminance = (299 * red + 587 * green + 114 * blue) // 1000
    saturation = brightest - darkest
    return luminance <= 155 or (saturation >= 58 and luminance <= 236)


def _runs(columns: Iterable[bool]) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for index, active in enumerate(columns):
        if active and start is None:
            start = index
        elif not active and start is not None:
            runs.append((start, index))
            start = None
    if start is not None:
        runs.append((start, index + 1))
    return runs


def _merge_nearby(runs: list[tuple[int, int]], *, max_gap: int) -> list[tuple[int, int]]:
    if not runs:
        return []
    merged = [runs[0]]
    for left, right in runs[1:]:
        previous_left, previous_right = merged[-1]
        if left - previous_right <= max_gap:
            merged[-1] = (previous_left, right)
        else:
            merged.append((left, right))
    return merged


def _candidate_bounds(
    rgba: bytes,
    width: int,
    left: int,
    right: int,
    top: int,
    bottom: int,
) -> tuple[int, int, int, int, int] | None:
    points: list[tuple[int, int]] = []
    for y in range(top, bottom):
        for x in range(left, right):
            offset = (y * width + x) * 4
            if _foreground(rgba[offset], rgba[offset + 1], rgba[offset + 2]):
                points.append((x, y))
    if not points:
        return None
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), min(ys), max(xs) + 1, max(ys) + 1, len(points)


def _nms(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Suppress duplicate/overlapping card candidates deterministically."""
    accepted: list[dict[str, Any]] = []
    for candidate in sorted(candidates, key=lambda item: (-float(item["confidence"]), item["bbox"][0])):
        left, top, right, bottom = candidate["bbox"]
        area = (right - left) * (bottom - top)
        duplicate = False
        for existing in accepted:
            other_left, other_top, other_right, other_bottom = existing["bbox"]
            overlap_left = max(left, other_left)
            overlap_top = max(top, other_top)
            overlap_right = min(right, other_right)
            overlap_bottom = min(bottom, other_bottom)
            overlap = max(0.0, overlap_right - overlap_left) * max(0.0, overlap_bottom - overlap_top)
            other_area = (other_right - other_left) * (other_bottom - other_top)
            union = area + other_area - overlap
            if union and overlap / union >= 0.55:
                duplicate = True
                break
        if not duplicate:
            accepted.append(candidate)
    # Slot rows are visually separated by far more than 8% of client height;
    # within a row, top pixels vary with artwork, so assign IDs left-to-right.
    return sorted(
        accepted,
        key=lambda item: (round(((item["bbox"][1] + item["bbox"][3]) / 2) / 0.08), item["bbox"][0]),
    )


def detect_build_option_slots(
    rgba: bytes,
    width: int,
    height: int,
    region_catalog: RegionCatalog,
) -> list[dict[str, Any]]:
    """Detect repeated Build Menu slots from a fresh client-area RGBA frame.

    The only search space is the upper portion of the existing
    ``build_controls`` region.  This keeps the detector out of the map, the
    top-right close control, and the bottom persistent HUD.  Every emitted
    bbox is recalculated from this exact frame.
    """
    if width <= 0 or height <= 0 or len(rgba) != width * height * 4:
        return []
    controls = region_catalog.get("build_controls")
    roi_left, roi_top, roi_right, roi_bottom = controls.crop_box(width, height)
    content_top = roi_top + round((roi_bottom - roi_top) * 0.05)
    content_bottom = roi_top + round((roi_bottom - roi_top) * 0.50)
    if roi_left >= roi_right or content_bottom - content_top < _MIN_HEIGHT_PX:
        return []
    column_counts: list[int] = []
    for x in range(roi_left, roi_right):
        count = 0
        for y in range(content_top, content_bottom):
            offset = (y * width + x) * 4
            if _foreground(rgba[offset], rgba[offset + 1], rgba[offset + 2]):
                count += 1
        column_counts.append(count)
    raw_runs = _runs(count >= _MIN_COMPONENT_PIXELS_PER_COLUMN for count in column_counts)
    runs = _merge_nearby(raw_runs, max_gap=_MERGE_GAP_PX)
    candidates: list[dict[str, Any]] = []
    max_width = max(_MIN_WIDTH_PX, round(width * _MAX_WIDTH_RATIO))
    max_height = max(_MIN_HEIGHT_PX, round(height * _MAX_HEIGHT_RATIO))
    for local_left, local_right in runs:
        left, right = roi_left + local_left, roi_left + local_right
        bounds = _candidate_bounds(rgba, width, left, right, content_top, content_bottom)
        if bounds is None:
            continue
        box_left, box_top, box_right, box_bottom, pixels = bounds
        box_width = box_right - box_left
        box_height = box_bottom - box_top
        if not (_MIN_WIDTH_PX <= box_width <= max_width and _MIN_HEIGHT_PX <= box_height <= max_height):
            continue
        if not 0.45 <= box_width / box_height <= 3.0:
            continue
        if box_top == content_top or box_bottom == content_bottom:
            continue
        fill = pixels / float(box_width * box_height)
        confidence = min(0.99, max(0.90, 0.90 + min(0.04, fill * 0.08) + min(0.05, box_height / height * 0.4)))
        bbox = [box_left / width, box_top / height, box_right / width, box_bottom / height]
        if not 0.0 <= bbox[0] < bbox[2] <= 1.0 or not 0.0 <= bbox[1] < bbox[3] <= 1.0:
            continue
        candidates.append({
            "bbox": bbox,
            "global_bbox": list(bbox),
            "confidence": confidence,
            "locked": None,
            "costs": {},
            "resolver": "deterministic_current_frame_option_slot",
            "region": "build_controls",
        })
    slots: list[dict[str, Any]] = []
    for index, candidate in enumerate(_nms(candidates), start=1):
        identifier = f"build_option_slot_{index:02d}"
        slots.append({
            "id": identifier,
            "canonical_id": identifier,
            "raw_id": identifier,
            "role": "BUILD_OPTION",
            "label": "unknown",
            **candidate,
        })
    return slots


def detect_build_category_tabs(
    rgba: bytes,
    width: int,
    height: int,
    region_catalog: RegionCatalog,
) -> list[dict[str, Any]]:
    """Return current-frame category-card geometry without semantic guessing.

    The root Build Menu uses the same repeated-card visual structure as the
    category page.  This wrapper deliberately re-runs the local detector on
    *this* frame and changes only its role and non-semantic identity.  It never
    converts a previous calibration bbox into an actionable current target.
    """
    categories: list[dict[str, Any]] = []
    for index, slot in enumerate(detect_build_option_slots(rgba, width, height, region_catalog), start=1):
        identifier = f"build_category_tab_{index:02d}"
        categories.append({
            **slot,
            "id": identifier,
            "canonical_id": identifier,
            "raw_id": identifier,
            "role": "BUILD_CATEGORY_TAB",
            "label": "unknown",
            "resolver": "deterministic_current_frame_category_tab",
        })
    return categories
