"""Pure, fail-closed planning for one Build Menu category click.

This module accepts an already captured :class:`BuildMenuSnapshot`; it cannot
capture the game, call an AI model, or emit input.  Its plan is intentionally
short-lived and must be rebuilt from a fresh current-frame snapshot before a
live action is considered.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .build_menu import BuildCategory, BuildMenuSnapshot, BuildMenuState, MIN_ACTIONABLE_CONFIDENCE


class CategoryNavigationError(ValueError):
    """Raised when a snapshot cannot safely produce a category click plan."""


@dataclass(frozen=True)
class CategoryClickPlan:
    frame_id: str
    hwnd: int
    pid: int
    category_id: str
    bbox: tuple[float, float, float, float]
    global_bbox: tuple[float, float, float, float]
    click_point: tuple[float, float]
    confidence: float
    geometry: dict[str, Any]
    safe_click_box: tuple[float, float, float, float]

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        for key in ("bbox", "global_bbox", "click_point", "safe_click_box"):
            value[key] = list(value[key])
        return value


def _inside_client(bbox: tuple[float, float, float, float]) -> bool:
    left, top, right, bottom = bbox
    return 0.0 <= left < right <= 1.0 and 0.0 <= top < bottom <= 1.0


def _edge_margin(bbox: tuple[float, float, float, float]) -> float:
    return min(bbox[0], bbox[1], 1.0 - bbox[2], 1.0 - bbox[3])


def _safe_center_box(bbox: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    """Return the inner 40 percent click-safe box for an actionable category."""
    left, top, right, bottom = bbox
    width, height = right - left, bottom - top
    return (
        left + width * 0.30,
        top + height * 0.30,
        right - width * 0.30,
        bottom - height * 0.30,
    )


def _candidate_key(category: BuildCategory) -> tuple[float, float, float, str]:
    bbox = category.global_bbox or category.bbox
    width, height = bbox[2] - bbox[0], bbox[3] - bbox[1]
    # Higher confidence and greater distance from screen edges win.  A normal
    # area is a final deterministic tie-breaker, then the stable local ID.
    return (-category.confidence, -_edge_margin(bbox), -(width * height), category.id)


def plan_build_category_click(snapshot: BuildMenuSnapshot, *, frame_id: str) -> CategoryClickPlan:
    """Build exactly one safe category click plan from a fresh local snapshot."""
    if not isinstance(frame_id, str) or not frame_id.strip():
        raise CategoryNavigationError("category plan requires a non-empty current frame_id")
    if snapshot.state is not BuildMenuState.ROOT_OPEN:
        raise CategoryNavigationError(f"category plan requires ROOT_OPEN, got {snapshot.state.value}")
    if snapshot.geometry is None:
        raise CategoryNavigationError("category plan requires current frame geometry")
    if snapshot.evidence.get("category_source") != "deterministic_current_frame_category_tab":
        raise CategoryNavigationError("category plan rejects non-current-frame category evidence")

    candidates: list[BuildCategory] = []
    for category in snapshot.categories:
        bbox = category.global_bbox or category.bbox
        if category.confidence < MIN_ACTIONABLE_CONFIDENCE or not _inside_client(bbox):
            continue
        if _edge_margin(bbox) < 0.02:
            continue
        if (bbox[2] - bbox[0]) < 0.02 or (bbox[3] - bbox[1]) < 0.02:
            continue
        candidates.append(category)
    if not candidates:
        raise CategoryNavigationError("no current-frame actionable BUILD_CATEGORY_TAB candidate")

    selected = sorted(candidates, key=_candidate_key)[0]
    bbox = selected.global_bbox or selected.bbox
    safe_box = _safe_center_box(bbox)
    click_point = ((safe_box[0] + safe_box[2]) / 2.0, (safe_box[1] + safe_box[3]) / 2.0)
    if not _inside_client((click_point[0], click_point[1], click_point[0] + 0.000001, click_point[1] + 0.000001)):
        raise CategoryNavigationError("computed category click point is outside client bounds")
    geometry = snapshot.geometry
    return CategoryClickPlan(
        frame_id=frame_id,
        hwnd=geometry.hwnd,
        pid=geometry.pid,
        category_id=selected.id,
        bbox=selected.bbox,
        global_bbox=bbox,
        click_point=click_point,
        confidence=selected.confidence,
        geometry=geometry.to_dict(),
        safe_click_box=safe_box,
    )
