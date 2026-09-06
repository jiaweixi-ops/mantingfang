"""Read-only Build Menu state and structure parsing.

This module deliberately stops at the current-frame model boundary.  It does
not capture a window, call a model, resolve a click, or send input.  Later
navigation phases can consume :class:`BuildMenuSnapshot` after adding their
own foreground and geometry safety gates.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any, Mapping


MIN_ACTIONABLE_CONFIDENCE = 0.90


class BuildMenuState(StrEnum):
    UNKNOWN = "unknown"
    CLOSED = "closed"
    ROOT_OPEN = "root_open"
    CATEGORY_OPEN = "category_open"
    BUILDING_SELECTED = "building_selected"


class BuildMenuSchemaError(ValueError):
    """Raised when a current-frame menu observation is structurally invalid."""


@dataclass(frozen=True)
class FrameGeometry:
    """The geometry identity attached to one captured frame."""

    hwnd: int
    pid: int
    client_width: int
    client_height: int
    client_origin: tuple[int, int]
    dpi: int = 96
    captured_at: str = ""

    def __post_init__(self) -> None:
        if self.hwnd <= 0 or self.pid <= 0:
            raise BuildMenuSchemaError("frame geometry requires positive hwnd and pid")
        if self.client_width <= 0 or self.client_height <= 0:
            raise BuildMenuSchemaError("frame geometry requires positive client size")
        if len(self.client_origin) != 2:
            raise BuildMenuSchemaError("frame geometry client_origin must have two values")
        if self.dpi <= 0:
            raise BuildMenuSchemaError("frame geometry dpi must be positive")

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["client_origin"] = list(self.client_origin)
        return value


@dataclass(frozen=True)
class BuildCategory:
    id: str
    label: str
    bbox: tuple[float, float, float, float]
    confidence: float
    global_bbox: tuple[float, float, float, float] | None = None

    def to_dict(self) -> dict[str, Any]:
        return _tuple_bboxes_to_lists(asdict(self))


@dataclass(frozen=True)
class BuildOption:
    id: str
    label: str
    bbox: tuple[float, float, float, float]
    confidence: float
    locked: bool | None = None
    costs: dict[str, int | float] = field(default_factory=dict)
    global_bbox: tuple[float, float, float, float] | None = None

    def to_dict(self) -> dict[str, Any]:
        return _tuple_bboxes_to_lists(asdict(self))


@dataclass(frozen=True)
class BuildMenuSnapshot:
    state: BuildMenuState
    current_screen: str
    categories: tuple[BuildCategory, ...]
    options: tuple[BuildOption, ...]
    geometry: FrameGeometry | None
    open_control: dict[str, Any] | None = None
    close_control: dict[str, Any] | None = None
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "current_screen": self.current_screen,
            "categories": [item.to_dict() for item in self.categories],
            "options": [item.to_dict() for item in self.options],
            "geometry": self.geometry.to_dict() if self.geometry else None,
            "open_control": self.open_control,
            "close_control": self.close_control,
            "evidence": self.evidence,
        }


def _tuple_bboxes_to_lists(value: dict[str, Any]) -> dict[str, Any]:
    for key in ("bbox", "global_bbox"):
        if isinstance(value.get(key), tuple):
            value[key] = list(value[key])
    return value


def _confidence(value: Any, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BuildMenuSchemaError(f"{field_name} must be numeric")
    result = float(value)
    if not 0.0 <= result <= 1.0:
        raise BuildMenuSchemaError(f"{field_name} must be between 0 and 1")
    return result


def _bbox(value: Any, *, field_name: str) -> tuple[float, float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise BuildMenuSchemaError(f"{field_name} must contain four normalized values")
    try:
        result = tuple(float(item) for item in value)
    except (TypeError, ValueError) as exc:
        raise BuildMenuSchemaError(f"{field_name} values must be numeric") from exc
    left, top, right, bottom = result
    if not 0.0 <= left < right <= 1.0 or not 0.0 <= top < bottom <= 1.0:
        raise BuildMenuSchemaError(f"{field_name} must be a normalized non-empty bbox")
    return result


def _text(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BuildMenuSchemaError(f"{field_name} must be a non-empty string")
    return value.strip()


def _element_bbox(raw: Mapping[str, Any], *, field_name: str) -> tuple[tuple[float, float, float, float], tuple[float, float, float, float] | None]:
    local = raw.get("bbox")
    global_value = raw.get("global_bbox")
    if local is None and global_value is None:
        raise BuildMenuSchemaError(f"{field_name} requires bbox or global_bbox")
    local_bbox = _bbox(local if local is not None else global_value, field_name=f"{field_name}.bbox")
    global_bbox = _bbox(global_value, field_name=f"{field_name}.global_bbox") if global_value is not None else None
    return local_bbox, global_bbox


def _geometry(value: Any) -> FrameGeometry | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise BuildMenuSchemaError("geometry must be an object")
    size = value.get("client_size")
    width = value.get("client_width")
    height = value.get("client_height")
    if size is not None:
        if not isinstance(size, (list, tuple)) or len(size) != 2:
            raise BuildMenuSchemaError("geometry.client_size must contain width and height")
        width, height = size
    origin = value.get("client_origin", (0, 0))
    if not isinstance(origin, (list, tuple)) or len(origin) != 2:
        raise BuildMenuSchemaError("geometry.client_origin must contain x and y")
    try:
        geometry = FrameGeometry(
            hwnd=int(value["hwnd"]),
            pid=int(value["pid"]),
            client_width=int(width),
            client_height=int(height),
            client_origin=(int(origin[0]), int(origin[1])),
            dpi=int(value.get("dpi", 96)),
            captured_at=str(value.get("captured_at", value.get("timestamp", ""))),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise BuildMenuSchemaError("geometry is missing valid hwnd, pid, or client size") from exc
    return geometry


def _role(raw: Mapping[str, Any]) -> str:
    return str(raw.get("role", "")).strip().upper()


def _confidence_ok(raw: Mapping[str, Any], threshold: float) -> bool:
    value = raw.get("confidence")
    return isinstance(value, (int, float)) and not isinstance(value, bool) and float(value) >= threshold


def _valid_element(raw: Any, roles: set[str], threshold: float) -> bool:
    if not isinstance(raw, Mapping) or _role(raw) not in roles or not _confidence_ok(raw, threshold):
        return False
    try:
        _text(raw.get("id", raw.get("canonical_id")), field_name="ui element id")
        _element_bbox(raw, field_name="ui element")
    except BuildMenuSchemaError:
        return False
    return True


def _elements(observation: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw = observation.get("ui_elements")
    if not isinstance(raw, list):
        raise BuildMenuSchemaError("ui_elements must be a list")
    if any(not isinstance(item, Mapping) for item in raw):
        raise BuildMenuSchemaError("each ui element must be an object")
    return list(raw)


def _first_valid(elements: list[Mapping[str, Any]], roles: set[str], threshold: float) -> Mapping[str, Any] | None:
    return next((item for item in elements if _valid_element(item, roles, threshold)), None)


def _open_evidence(observation: Mapping[str, Any], elements: list[Mapping[str, Any]], threshold: float) -> dict[str, Any]:
    close_control = _first_valid(elements, {"BUILD_MENU_CLOSE", "BUILD_MENU_TOGGLE"}, threshold)
    categories = [item for item in elements if _valid_element(item, {"BUILD_CATEGORY_TAB"}, threshold)]
    options = [item for item in elements if _valid_element(item, {"BUILD_OPTION", "BUILD_DISABLED_OPTION"}, threshold)]
    panel_visible = observation.get("build_panel_visible") is True and _confidence_ok(
        {"confidence": observation.get("build_panel_confidence", observation.get("confidence"))}, threshold
    )
    return {
        "close_control": close_control is not None,
        "categories": len(categories),
        "options": len(options),
        "panel_visible": panel_visible,
    }


def detect_build_menu_state(
    observation: Mapping[str, Any],
    *,
    min_confidence: float = MIN_ACTIONABLE_CONFIDENCE,
) -> BuildMenuState:
    """Classify one current-frame observation using strong local evidence.

    A model-provided ``build_menu_open`` flag alone is never enough to mark the
    menu open.  Conflicting flags, missing structure, invalid bboxes, and low
    confidence all resolve to ``UNKNOWN``.
    """

    if not isinstance(observation, Mapping):
        raise BuildMenuSchemaError("observation must be an object")
    if not 0.0 < min_confidence <= 1.0:
        raise BuildMenuSchemaError("min_confidence must be between 0 and 1")
    elements = _elements(observation)
    open_flag = observation.get("build_menu_open")
    if not isinstance(open_flag, bool):
        return BuildMenuState.UNKNOWN
    evidence = _open_evidence(observation, elements, min_confidence)
    strong_open = evidence["close_control"] and (
        evidence["panel_visible"] or evidence["categories"] > 0 or evidence["options"] > 0
    )
    strong_closed = open_flag is False and _first_valid(
        elements, {"BUILD_MENU_OPEN", "BUILD_MENU_TOGGLE"}, min_confidence
    ) is not None and not strong_open
    if strong_open and open_flag is not True:
        return BuildMenuState.UNKNOWN
    if strong_closed:
        return BuildMenuState.CLOSED
    if not strong_open:
        return BuildMenuState.UNKNOWN

    placement = observation.get("placement_mode")
    selected = observation.get("building_selected")
    placement_confidence = observation.get("placement_confidence", observation.get("confidence"))
    if (placement is True or selected is True) and isinstance(placement_confidence, (int, float)) and not isinstance(placement_confidence, bool) and float(placement_confidence) >= min_confidence:
        return BuildMenuState.BUILDING_SELECTED
    if evidence["options"] > 0 or observation.get("active_category"):
        return BuildMenuState.CATEGORY_OPEN
    return BuildMenuState.ROOT_OPEN


def _parse_category(raw: Mapping[str, Any], index: int) -> BuildCategory:
    local_bbox, global_bbox = _element_bbox(raw, field_name=f"category[{index}]")
    identifier = _text(raw.get("id", raw.get("canonical_id")), field_name=f"category[{index}].id")
    label = _text(raw.get("label"), field_name=f"category[{index}].label")
    return BuildCategory(identifier, label, local_bbox, _confidence(raw.get("confidence"), field_name=f"category[{index}].confidence"), global_bbox)


def _parse_costs(raw: Any, index: int) -> dict[str, int | float]:
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise BuildMenuSchemaError(f"option[{index}].costs must be an object")
    costs: dict[str, int | float] = {}
    for key, value in raw.items():
        name = _text(key, field_name=f"option[{index}].cost name")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or float(value) < 0:
            raise BuildMenuSchemaError(f"option[{index}].costs values must be non-negative numbers")
        costs[name] = value
    return costs


def _parse_option(raw: Mapping[str, Any], index: int) -> BuildOption:
    local_bbox, global_bbox = _element_bbox(raw, field_name=f"option[{index}]")
    identifier = _text(raw.get("id", raw.get("canonical_id")), field_name=f"option[{index}].id")
    label = _text(raw.get("label"), field_name=f"option[{index}].label")
    locked = raw.get("locked")
    if locked is not None and not isinstance(locked, bool):
        raise BuildMenuSchemaError(f"option[{index}].locked must be bool or null")
    return BuildOption(
        identifier,
        label,
        local_bbox,
        _confidence(raw.get("confidence"), field_name=f"option[{index}].confidence"),
        locked,
        _parse_costs(raw.get("costs"), index),
        global_bbox,
    )


def _structured_items(observation: Mapping[str, Any], key: str, roles: set[str]) -> list[Mapping[str, Any]]:
    explicit = observation.get(key)
    if explicit is not None:
        if not isinstance(explicit, list):
            raise BuildMenuSchemaError(f"{key} must be a list")
        if any(not isinstance(item, Mapping) for item in explicit):
            raise BuildMenuSchemaError(f"each {key} item must be an object")
        return list(explicit)
    return [item for item in _elements(observation) if _role(item) in roles]


def parse_build_menu_snapshot(
    observation: Mapping[str, Any],
    *,
    geometry: Mapping[str, Any] | FrameGeometry | None = None,
    min_confidence: float = MIN_ACTIONABLE_CONFIDENCE,
) -> BuildMenuSnapshot:
    """Parse one fresh observation into a strict, serializable menu snapshot."""

    if not isinstance(observation, Mapping):
        raise BuildMenuSchemaError("observation must be an object")
    current_screen = _text(observation.get("current_screen"), field_name="current_screen")
    state = detect_build_menu_state(observation, min_confidence=min_confidence)
    categories = tuple(
        _parse_category(item, index)
        for index, item in enumerate(_structured_items(observation, "categories", {"BUILD_CATEGORY_TAB"}))
    )
    options = tuple(
        _parse_option(item, index)
        for index, item in enumerate(_structured_items(observation, "building_options", {"BUILD_OPTION", "BUILD_DISABLED_OPTION"}))
    )
    parsed_geometry = geometry if isinstance(geometry, FrameGeometry) else _geometry(
        geometry if geometry is not None else observation.get("geometry")
    )
    evidence = _open_evidence(observation, _elements(observation), min_confidence)
    elements = _elements(observation)
    open_control = next(
        (dict(item) for item in elements if _valid_element(item, {"BUILD_MENU_OPEN", "BUILD_MENU_TOGGLE"}, min_confidence)),
        None,
    )
    close_control = next(
        (dict(item) for item in elements if _valid_element(item, {"BUILD_MENU_CLOSE", "BUILD_MENU_TOGGLE"}, min_confidence)),
        None,
    )
    return BuildMenuSnapshot(
        state,
        current_screen,
        categories,
        options,
        parsed_geometry,
        open_control,
        close_control,
        evidence,
    )
