from __future__ import annotations

from ai_governor.build_menu import BuildCategory, BuildMenuSnapshot, BuildMenuState, BuildOption, FrameGeometry
from ai_governor.build_menu_observer import _resolve_local_menu_control, _track_bbox, assess_phase_snapshots
from ai_governor.perception import RegionCatalog


def _geometry() -> FrameGeometry:
    return FrameGeometry(100, 200, 64, 64, (10, 20), 96, "2026-09-06T12:00:00Z")


def _control(identifier: str, role: str, bbox: list[float]) -> dict:
    return {
        "id": identifier,
        "canonical_id": identifier,
        "role": role,
        "bbox": bbox,
        "global_bbox": bbox,
        "confidence": 0.95,
    }


def _closed_snapshot(x_shift: float = 0.0) -> BuildMenuSnapshot:
    control = _control("build_menu_open_control", "BUILD_MENU_OPEN", [0.10 + x_shift, 0.10, 0.20 + x_shift, 0.20])
    return BuildMenuSnapshot(
        BuildMenuState.CLOSED,
        "城市",
        (),
        (),
        _geometry(),
        control,
        None,
        {"close_control": False},
    )


def _root_snapshot() -> BuildMenuSnapshot:
    close = _control("build_menu_close_control", "BUILD_MENU_CLOSE", [0.80, 0.10, 0.90, 0.20])
    category = BuildCategory("build_category_tab_food", "食物", (0.10, 0.80, 0.20, 0.90), 0.95, (0.10, 0.80, 0.20, 0.90))
    return BuildMenuSnapshot(
        BuildMenuState.ROOT_OPEN,
        "建筑菜单",
        (category,),
        (),
        _geometry(),
        None,
        close,
        {"close_control": True},
    )


def test_phase_assessment_requires_three_stable_current_frame_snapshots() -> None:
    result = assess_phase_snapshots("closed", [_closed_snapshot(), _closed_snapshot(), _closed_snapshot()])
    assert result["stable"] is True
    assert result["samples"] == 3

    changed_geometry = BuildMenuSnapshot(
        BuildMenuState.CLOSED,
        "城市",
        (),
        (),
        FrameGeometry(101, 201, 64, 64, (10, 20), 96, "2026-09-06T12:00:01Z"),
        _closed_snapshot().open_control,
        None,
        {},
    )
    assert assess_phase_snapshots("closed", [_closed_snapshot(), _closed_snapshot(), changed_geometry])["stable"] is False


def test_phase_assessment_requires_real_category_geometry() -> None:
    assert assess_phase_snapshots("root", [_root_snapshot(), _root_snapshot(), _root_snapshot()])["stable"] is True
    assert assess_phase_snapshots("root", [_closed_snapshot(), _closed_snapshot(), _closed_snapshot()])["stable"] is False


def test_category_assessment_rejects_center_drift_even_when_slot_id_matches() -> None:
    base = _root_snapshot()
    option = BuildOption("build_option_slot_01", "unknown", (0.20, 0.70, 0.30, 0.80), 0.95, None, {})
    drifting = BuildOption("build_option_slot_01", "unknown", (0.30, 0.70, 0.40, 0.80), 0.95, None, {})
    category = BuildMenuSnapshot(BuildMenuState.CATEGORY_OPEN, "建筑菜单", (), (option,), base.geometry, None, base.close_control, {})
    changed = BuildMenuSnapshot(BuildMenuState.CATEGORY_OPEN, "建筑菜单", (), (drifting,), base.geometry, None, base.close_control, {})
    assert assess_phase_snapshots("category", [category, changed, changed])["stable"] is False


def test_template_tracker_returns_a_bbox_from_the_fresh_frame() -> None:
    width = height = 64
    reference = bytearray([0, 0, 0, 255] * (width * height))
    current = bytearray([0, 0, 0, 255] * (width * height))

    def paint(buffer: bytearray, left: int, top: int) -> None:
        for y in range(top, top + 8):
            for x in range(left, left + 8):
                offset = (y * width + x) * 4
                buffer[offset:offset + 4] = bytes((220, 160, 40, 255))

    paint(reference, 16, 16)
    paint(current, 18, 17)
    bbox, confidence = _track_bbox(bytes(reference), bytes(current), width, height, [0.25, 0.25, 0.375, 0.375], search_radius=4)
    assert bbox == [18 / 64, 17 / 64, 26 / 64, 25 / 64]
    assert confidence >= 0.99


def test_local_control_resolver_uses_current_red_close_patch() -> None:
    width = height = 64
    frame = bytearray([30, 30, 30, 255] * (width * height))
    for y in range(6, 14):
        for x in range(54, 64):
            offset = (y * width + x) * 4
            frame[offset:offset + 4] = bytes((210, 60, 45, 255))
    control = _resolve_local_menu_control(bytes(frame), width, height, RegionCatalog())
    assert control is not None
    assert control["role"] == "BUILD_MENU_CLOSE"
    assert control["region"] == "build_entry"
    assert control["confidence"] >= 0.90
    assert control["global_bbox"] == [56 / 64, 6 / 64, 64 / 64, 14 / 64]


def test_local_control_resolver_uses_real_lower_build_toggle_as_non_close_evidence() -> None:
    width = height = 128
    frame = bytearray([210, 200, 180, 255] * (width * height))
    for y in range(103, 117):
        for x in range(108, 120):
            offset = (y * width + x) * 4
            frame[offset:offset + 4] = bytes((210, 60, 45, 255))
    control = _resolve_local_menu_control(bytes(frame), width, height, RegionCatalog())
    assert control is not None
    assert control["role"] == "BUILD_MENU_TOGGLE"
    assert control["region"] == "build_controls"
    assert control["raw_id"] == "local_red_toggle_control"
    assert control["confidence"] >= 0.90
