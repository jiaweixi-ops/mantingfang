from __future__ import annotations

from ai_governor.build_option_detector import _nms, detect_build_category_tabs, detect_build_option_slots
from ai_governor.perception import RegionCatalog


def _frame(width: int = 1280, height: int = 960) -> bytearray:
    return bytearray([232, 220, 190, 255] * (width * height))


def _paint(frame: bytearray, width: int, left: int, top: int, right: int, bottom: int, color: tuple[int, int, int] = (58, 96, 72)) -> None:
    for y in range(top, bottom):
        for x in range(left, right):
            offset = (y * width + x) * 4
            frame[offset:offset + 4] = bytes((*color, 255))


def test_detects_repeated_current_frame_option_slots_only_in_build_controls_content() -> None:
    width, height = 1280, 960
    frame = _frame(width, height)
    for left, right in ((70, 180), (290, 410), (520, 645)):
        _paint(frame, width, left, 660, right, 755)
    slots = detect_build_option_slots(bytes(frame), width, height, RegionCatalog())
    assert [slot["id"] for slot in slots] == ["build_option_slot_01", "build_option_slot_02", "build_option_slot_03"]
    assert [slot["bbox"][0] for slot in slots] == sorted(slot["bbox"][0] for slot in slots)
    assert all(slot["role"] == "BUILD_OPTION" for slot in slots)
    assert all(slot["label"] == "unknown" for slot in slots)
    assert all(slot["locked"] is None and slot["costs"] == {} for slot in slots)
    assert all(slot["confidence"] >= 0.90 for slot in slots)
    assert all(0 <= slot["global_bbox"][0] < slot["global_bbox"][2] <= 1 for slot in slots)
    assert all(0 <= slot["global_bbox"][1] < slot["global_bbox"][3] <= 1 for slot in slots)


def test_ignores_root_tabs_closed_controls_and_map_ui_outside_option_content_band() -> None:
    width, height = 1280, 960
    frame = _frame(width, height)
    # Root-category tabs and persistent map HUD are below the option band.
    _paint(frame, width, 80, 820, 180, 910)
    _paint(frame, width, 350, 825, 455, 910)
    # The red close control is in the upper client area, outside build_controls.
    _paint(frame, width, 1220, 108, 1275, 155, (208, 62, 44))
    assert detect_build_option_slots(bytes(frame), width, height, RegionCatalog()) == []


def test_rejects_too_small_too_wide_and_boundary_touching_candidates() -> None:
    width, height = 1280, 960
    frame = _frame(width, height)
    _paint(frame, width, 50, 660, 82, 755)      # too narrow
    _paint(frame, width, 160, 660, 900, 755)    # too wide
    _paint(frame, width, 970, 641, 1090, 755)   # touches the option-band top
    assert detect_build_option_slots(bytes(frame), width, height, RegionCatalog()) == []


def test_nms_discards_overlapping_candidate() -> None:
    candidates = [
        {"bbox": [0.10, 0.70, 0.20, 0.80], "confidence": 0.97},
        {"bbox": [0.11, 0.70, 0.21, 0.80], "confidence": 0.95},
        {"bbox": [0.30, 0.70, 0.40, 0.80], "confidence": 0.94},
    ]
    result = _nms(candidates)
    assert [item["bbox"] for item in result] == [[0.10, 0.70, 0.20, 0.80], [0.30, 0.70, 0.40, 0.80]]


def test_category_tabs_are_redetected_on_this_frame_not_loaded_from_calibration() -> None:
    width, height = 1280, 960
    frame = _frame(width, height)
    _paint(frame, width, 90, 660, 190, 755)
    tabs = detect_build_category_tabs(bytes(frame), width, height, RegionCatalog())
    assert len(tabs) == 1
    assert tabs[0]["id"] == "build_category_tab_01"
    assert tabs[0]["role"] == "BUILD_CATEGORY_TAB"
    assert tabs[0]["resolver"] == "deterministic_current_frame_category_tab"
    assert tabs[0]["confidence"] >= 0.90
