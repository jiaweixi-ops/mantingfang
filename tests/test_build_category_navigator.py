from __future__ import annotations

import pytest

from ai_governor.build_category_navigator import CategoryNavigationError, plan_build_category_click
from ai_governor.build_menu import BuildCategory, BuildMenuSnapshot, BuildMenuState, FrameGeometry


def _snapshot(*categories: BuildCategory, state: BuildMenuState = BuildMenuState.ROOT_OPEN, source: str = "deterministic_current_frame_category_tab") -> BuildMenuSnapshot:
    geometry = FrameGeometry(101, 202, 1280, 960, (50, 80), 96, "2026-09-06T12:00:00Z")
    close = {
        "id": "build_menu_close_control",
        "role": "BUILD_MENU_CLOSE",
        "bbox": [0.90, 0.08, 0.95, 0.14],
        "global_bbox": [0.90, 0.08, 0.95, 0.14],
        "confidence": 0.98,
    }
    return BuildMenuSnapshot(state, "建筑菜单", categories, (), geometry, None, close, {"category_source": source})


def _category(identifier: str, bbox: tuple[float, float, float, float], confidence: float = 0.95) -> BuildCategory:
    return BuildCategory(identifier, "unknown", bbox, confidence, bbox)


def test_planner_selects_a_current_frame_non_edge_category_and_clicks_center() -> None:
    edge = _category("build_category_tab_01", (0.021, 0.68, 0.10, 0.80), 0.99)
    central = _category("build_category_tab_04", (0.42, 0.68, 0.52, 0.80), 0.95)
    plan = plan_build_category_click(_snapshot(edge, central), frame_id="fresh-frame")
    assert plan.category_id == "build_category_tab_01"
    assert plan.click_point == pytest.approx((0.0605, 0.74))
    assert plan.safe_click_box == pytest.approx((0.0447, 0.716, 0.0763, 0.764))
    assert plan.hwnd == 101 and plan.pid == 202
    assert plan.geometry["client_origin"] == [50, 80]


def test_planner_rejects_non_root_stale_and_low_confidence_candidates() -> None:
    category = _category("build_category_tab_01", (0.20, 0.68, 0.30, 0.80))
    with pytest.raises(CategoryNavigationError, match="ROOT_OPEN"):
        plan_build_category_click(_snapshot(category, state=BuildMenuState.CATEGORY_OPEN), frame_id="fresh")
    with pytest.raises(CategoryNavigationError, match="non-current-frame"):
        plan_build_category_click(_snapshot(category, source="calibration_json"), frame_id="fresh")
    with pytest.raises(CategoryNavigationError, match="no current-frame"):
        plan_build_category_click(_snapshot(_category("weak", (0.20, 0.68, 0.30, 0.80), 0.89)), frame_id="fresh")


def test_planner_rejects_empty_frame_identifier() -> None:
    category = _category("build_category_tab_01", (0.20, 0.68, 0.30, 0.80))
    with pytest.raises(CategoryNavigationError, match="frame_id"):
        plan_build_category_click(_snapshot(category), frame_id="")
