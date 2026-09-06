from __future__ import annotations

import pytest

from ai_governor.build_menu import (
    BuildMenuSchemaError,
    BuildMenuState,
    FrameGeometry,
    detect_build_menu_state,
    parse_build_menu_snapshot,
)


def _element(identifier: str, role: str, label: str, confidence: float = 0.95) -> dict:
    return {
        "id": identifier,
        "role": role,
        "label": label,
        "bbox": [0.10, 0.10, 0.30, 0.30],
        "global_bbox": [0.10, 0.10, 0.30, 0.30],
        "confidence": confidence,
    }


def _open_observation(**extra: object) -> dict:
    value: dict = {
        "build_menu_open": True,
        "current_screen": "建筑菜单",
        "build_panel_visible": True,
        "build_panel_confidence": 0.96,
        "ui_elements": [
            _element("close", "BUILD_MENU_CLOSE", "关闭"),
            _element("food", "BUILD_CATEGORY_TAB", "食物"),
        ],
    }
    value.update(extra)
    return value


def test_state_detector_requires_strong_open_evidence() -> None:
    assert detect_build_menu_state(_open_observation()) is BuildMenuState.ROOT_OPEN
    assert detect_build_menu_state({
        "build_menu_open": True,
        "current_screen": "建筑菜单",
        "ui_elements": [_element("close", "BUILD_MENU_CLOSE", "关闭")],
    }) is BuildMenuState.UNKNOWN
    assert detect_build_menu_state({
        "build_menu_open": False,
        "current_screen": "城市",
        "ui_elements": [_element("entry", "BUILD_MENU_OPEN", "建造")],
    }) is BuildMenuState.CLOSED


def test_state_detector_classifies_category_and_selection() -> None:
    observation = _open_observation(
        active_category="food",
        building_options=[_element("farm", "BUILD_OPTION", "农田")],
    )
    assert detect_build_menu_state(observation) is BuildMenuState.CATEGORY_OPEN
    observation["placement_mode"] = True
    observation["placement_confidence"] = 0.95
    assert detect_build_menu_state(observation) is BuildMenuState.BUILDING_SELECTED


def test_low_confidence_and_conflicting_state_fail_closed() -> None:
    assert detect_build_menu_state({
        "build_menu_open": False,
        "current_screen": "城市",
        "ui_elements": [_element("entry", "BUILD_MENU_OPEN", "建造", confidence=0.89)],
    }) is BuildMenuState.UNKNOWN
    assert detect_build_menu_state({
        "build_menu_open": False,
        "current_screen": "城市",
        "build_panel_visible": True,
        "build_panel_confidence": 0.95,
        "ui_elements": [_element("close", "BUILD_MENU_CLOSE", "关闭")],
    }) is BuildMenuState.UNKNOWN


def test_parser_preserves_geometry_and_locked_costs() -> None:
    observation = _open_observation(
        active_category="food",
        building_options=[
            {
                **_element("farm", "BUILD_OPTION", "农田"),
                "locked": False,
                "costs": {"wood": 100, "stone": 20},
            },
            {
                **_element("school", "BUILD_DISABLED_OPTION", "书院"),
                "locked": True,
                "costs": {"gold": 500},
            },
        ],
    )
    geometry = FrameGeometry(1234, 5678, 1280, 960, (98, 90), 96, "2026-09-06T12:00:00Z")
    snapshot = parse_build_menu_snapshot(observation, geometry=geometry)
    assert snapshot.state is BuildMenuState.CATEGORY_OPEN
    assert snapshot.geometry == geometry
    assert snapshot.options[0].costs == {"wood": 100, "stone": 20}
    assert snapshot.options[1].locked is True
    assert snapshot.to_dict()["geometry"]["client_origin"] == [98, 90]


def test_parser_rejects_malformed_structure() -> None:
    observation = _open_observation(
        building_options=[{**_element("farm", "BUILD_OPTION", "农田"), "costs": {"wood": -1}}]
    )
    with pytest.raises(BuildMenuSchemaError, match="non-negative"):
        parse_build_menu_snapshot(observation)

    with pytest.raises(BuildMenuSchemaError, match="current_screen"):
        parse_build_menu_snapshot({"build_menu_open": False, "ui_elements": []})

    with pytest.raises(BuildMenuSchemaError, match="each ui element"):
        parse_build_menu_snapshot({
            "build_menu_open": False,
            "current_screen": "城市",
            "ui_elements": [None],
        })


def test_module_is_read_only_model_boundary() -> None:
    source = __import__("ai_governor.build_menu", fromlist=["__file__"])
    text = open(source.__file__, encoding="utf-8").read()
    assert "SendInput" not in text
    assert "QwenClient" not in text
    assert "WindowsSendInput" not in text
