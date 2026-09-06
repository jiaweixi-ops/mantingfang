from __future__ import annotations

import pytest

from ai_governor.build_menu import BuildMenuSnapshot, BuildMenuState, BuildOption, FrameGeometry, detect_build_menu_state
from ai_governor.build_placement import (
    analyze_placement_transition,
    detect_current_frame_cancel_controls,
    placement_snapshot,
    validate_fresh_cancel_target,
)
from ai_governor.input import InputCommand, InputDisabled, InputSafetyMode, _enforce_safety_mode
from ai_governor.perception import RegionCatalog


def _geometry() -> FrameGeometry:
    return FrameGeometry(100, 200, 64, 64, (10, 20), 96, "2026-09-06T12:00:00Z")


def _frame(red_boxes: list[tuple[int, int, int, int]] = (), *, delta: bool = False) -> bytes:
    width = height = 64
    pixels = bytearray([210, 190, 150, 255] * (width * height))
    if delta:
        for y in range(12, 48):
            for x in range(14, 50):
                offset = (y * width + x) * 4
                pixels[offset:offset + 4] = bytes((40, 100, 180, 255))
    for left, top, right, bottom in red_boxes:
        for y in range(top, bottom):
            for x in range(left, right):
                offset = (y * width + x) * 4
                pixels[offset:offset + 4] = bytes((220, 45, 35, 255))
    return bytes(pixels)


def _category_snapshot(options: int = 1) -> BuildMenuSnapshot:
    items = tuple(
        BuildOption(
            f"build_option_slot_{index:02d}",
            "unknown",
            (0.10 + index * 0.10, 0.68, 0.18 + index * 0.10, 0.78),
            0.95,
            None,
            {},
        )
        for index in range(options)
    )
    return BuildMenuSnapshot(
        BuildMenuState.CATEGORY_OPEN,
        "建筑菜单",
        (),
        items,
        _geometry(),
        None,
        {"role": "BUILD_MENU_CLOSE", "confidence": 0.98},
        {},
    )


def test_category_open_without_placement_evidence_is_not_selected() -> None:
    assert detect_build_menu_state({
        "build_menu_open": True,
        "current_screen": "建筑菜单",
        "ui_elements": [{
            "id": "close", "role": "BUILD_MENU_CLOSE", "label": "关闭",
            "bbox": [0.8, 0.1, 0.9, 0.2], "confidence": 0.95,
        }],
        "building_options": [],
        "placement_mode": True,
        "placement_confidence": 0.95,
        "placement_evidence_count": 1,
    }) is BuildMenuState.UNKNOWN


def test_combined_placement_evidence_builds_selected_snapshot() -> None:
    evidence = type("Evidence", (), {
        "placement_mode": True,
        "confidence": 0.95,
        "evidence": ("new_current_frame_cancel_control", "category_options_transitioned"),
        "evidence_count": 2,
        "cancel_target": {"id": "cancel", "role": "BUILD_PLACEMENT_CANCEL", "confidence": 0.95,
                          "bbox": [0.8, 0.8, 0.9, 0.9]},
        "map_delta_score": 0.2,
        "baseline_options": 8,
        "current_options": 0,
        "to_dict": lambda self: {"evidence": list(self.evidence)},
    })()
    snapshot = placement_snapshot(evidence, geometry=_geometry(), frame_id="fresh")
    assert snapshot.state is BuildMenuState.BUILDING_SELECTED
    assert snapshot.placement_cancel is not None


def test_cancel_detector_is_current_frame_and_not_map_target() -> None:
    frame = _frame([(48, 48, 60, 60)])
    targets = detect_current_frame_cancel_controls(frame, 64, 64, RegionCatalog())
    assert targets
    assert targets[0]["role"] == "BUILD_PLACEMENT_CANCEL"
    assert targets[0]["source"] == "deterministic_current_frame_placement_cancel"
    assert "MAP_TARGET" not in targets[0]


def test_placement_transition_requires_cancel_and_two_signals() -> None:
    baseline = _frame()
    current = _frame([(48, 48, 60, 60)], delta=True)
    evidence = analyze_placement_transition(
        baseline, current, 64, 64, _category_snapshot(1), _category_snapshot(0), RegionCatalog()
    )
    assert evidence.placement_mode is True
    assert evidence.evidence_count >= 2


def test_stale_cancel_identity_and_geometry_are_rejected() -> None:
    target = {
        "role": "BUILD_PLACEMENT_CANCEL",
        "confidence": 0.95,
        "bbox": [0.8, 0.8, 0.9, 0.9],
        "frame_id": "old",
    }
    with pytest.raises(ValueError, match="stale"):
        validate_fresh_cancel_target(target, frame_id="new", current_frame_id="new", geometry=_geometry())
    target["frame_id"] = "new"
    target["geometry"] = {**_geometry().to_dict(), "hwnd": 999}
    with pytest.raises(ValueError, match="geometry"):
        validate_fresh_cancel_target(target, frame_id="new", current_frame_id="new", geometry=_geometry())


def test_placement_cancel_only_allows_only_fresh_cancel_role() -> None:
    allowed = InputCommand("click", 0.8, 0.8, target_role="BUILD_PLACEMENT_CANCEL")
    _enforce_safety_mode(InputSafetyMode.PLACEMENT_CANCEL_ONLY, allowed)
    for command in (
        InputCommand("click", 0.5, 0.5, target_role="BUILD_OPTION"),
        InputCommand("click", 0.5, 0.5, target_role="BUILD_CATEGORY_TAB"),
        InputCommand("click", 0.5, 0.5, target_role="MAP_TARGET"),
        InputCommand("key_down", key=27, target_role="BUILD_PLACEMENT_CANCEL"),
    ):
        with pytest.raises(InputDisabled):
            _enforce_safety_mode(InputSafetyMode.PLACEMENT_CANCEL_ONLY, command)


def test_placement_transition_does_not_claim_a_building_was_placed() -> None:
    evidence = analyze_placement_transition(
        _frame(), _frame([(48, 48, 60, 60)], delta=True), 64, 64,
        _category_snapshot(1), _category_snapshot(0), RegionCatalog()
    )
    assert evidence.placement_mode is True
    assert evidence.current_options == 0
