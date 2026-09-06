from __future__ import annotations

import json

import pytest

from ai_governor.build_menu import BuildMenuSnapshot, BuildMenuState, BuildOption, FrameGeometry
from ai_governor.build_placement_live_e2e import (
    BuildPlacementLiveError,
    _load_proven_slot,
    plan_build_option_click,
)


def _snapshot() -> BuildMenuSnapshot:
    geometry = FrameGeometry(100, 200, 1280, 960, (0, 0), 96, "now")
    option = BuildOption("build_option_slot_01", "unknown", (0.34, 0.72, 0.40, 0.84), 0.95, None, {})
    return BuildMenuSnapshot(
        BuildMenuState.CATEGORY_OPEN,
        "建筑菜单",
        (),
        (option,),
        geometry,
        None,
        None,
        {"option_source": "deterministic_current_frame_option_slot"},
    )


def test_manual_click_count_is_not_a_proven_slot(tmp_path) -> None:
    path = tmp_path / "e0.json"
    path.write_text(json.dumps({"manual_build_option_clicks": 1, "result": "PASS"}), encoding="utf-8")
    assert _load_proven_slot(path) is None


def test_legacy_semantic_sample_is_not_a_proven_slot(tmp_path) -> None:
    path = tmp_path / "e0.json"
    path.write_text(json.dumps({"proven_safe_slot": {"slot_id": "old_label", "basis": "legacy_semantic_sample"}}), encoding="utf-8")
    assert _load_proven_slot(path) is None


def test_plan_requires_explicit_current_frame_slot_identity() -> None:
    with pytest.raises(BuildPlacementLiveError, match="NOT_FOUND"):
        plan_build_option_click(
            _snapshot(),
            frame_id="fresh",
            proven_slot={"slot_id": "old_slot", "basis": "explicit_current_frame_slot_identity"},
        )


def test_plan_binds_explicit_slot_to_fresh_frame() -> None:
    plan = plan_build_option_click(
        _snapshot(),
        frame_id="fresh",
        proven_slot={"slot_id": "build_option_slot_01", "basis": "explicit_current_frame_slot_identity"},
    )
    assert plan.frame_id == "fresh"
    assert plan.provenance == "fresh_current_frame_proven_slot"
    assert plan.click_point == pytest.approx((0.37, 0.78))


def test_plan_rejects_non_current_option_evidence() -> None:
    snapshot = _snapshot()
    snapshot = BuildMenuSnapshot(
        snapshot.state,
        snapshot.current_screen,
        snapshot.categories,
        snapshot.options,
        snapshot.geometry,
        snapshot.open_control,
        snapshot.close_control,
        {},
        snapshot.placement_cancel,
    )
    with pytest.raises(BuildPlacementLiveError, match="non-current-frame"):
        plan_build_option_click(
            snapshot,
            frame_id="fresh",
            proven_slot={"slot_id": "build_option_slot_01", "basis": "explicit_current_frame_slot_identity"},
        )
