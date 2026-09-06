"""Strict semantic enrichment for current-frame Build Menu cards.

Geometry is owned by ``build_option_detector`` and is never accepted from a
model response.  This module only maps an existing slot identity to semantic
facts and conservative affordability results.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any, Mapping

from .build_menu import BuildOption


KNOWN_RESOURCES = frozenset({"gold", "rice", "vegetable", "wood", "stone"})


class SemanticSchemaError(ValueError):
    """Raised when a semantic result cannot be accepted without guessing."""


class AffordabilityStatus(StrEnum):
    AFFORDABLE = "AFFORDABLE"
    UNAFFORDABLE = "UNAFFORDABLE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class BuildOptionSemantic:
    slot_id: str
    label: str | None = None
    locked: bool | None = None
    costs: dict[str, int | float] | None = None
    confidence: float = 0.0
    sources: tuple[str, ...] = ("local_unknown",)
    diagnostics: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if not self.slot_id.strip():
            raise SemanticSchemaError("slot_id must be non-empty")
        if not 0.0 <= self.confidence <= 1.0:
            raise SemanticSchemaError("semantic confidence must be between 0 and 1")
        if self.label is not None and not self.label.strip():
            raise SemanticSchemaError("empty label must be null")
        if self.locked is not None and not isinstance(self.locked, bool):
            raise SemanticSchemaError("locked must be bool or null")
        normalized = self.costs or {}
        for resource, value in normalized.items():
            if resource not in KNOWN_RESOURCES:
                raise SemanticSchemaError(f"unknown resource: {resource}")
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
                raise SemanticSchemaError("costs must contain non-negative numbers")
        object.__setattr__(self, "costs", dict(normalized))
        object.__setattr__(self, "sources", tuple(self.sources))

    def to_dict(self) -> dict[str, Any]:
        return {
            "slot_id": self.slot_id,
            "label": self.label,
            "locked": self.locked,
            "costs": dict(self.costs or {}),
            "confidence": self.confidence,
            "sources": list(self.sources),
            "diagnostics": dict(self.diagnostics or {}),
        }


@dataclass(frozen=True)
class EnrichedBuildOption:
    geometry: BuildOption
    semantic: BuildOptionSemantic

    def __post_init__(self) -> None:
        if self.geometry.id != self.semantic.slot_id:
            raise SemanticSchemaError("semantic slot_id does not match geometry slot id")

    def to_dict(self) -> dict[str, Any]:
        return {"geometry": self.geometry.to_dict(), "semantic": self.semantic.to_dict()}


@dataclass(frozen=True)
class BuildAffordability:
    slot_id: str
    status: AffordabilityStatus
    missing_resources: dict[str, int | float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "slot_id": self.slot_id,
            "status": self.status.value,
            "missing_resources": dict(self.missing_resources),
        }


def unknown_semantic(slot_id: str, *, source: str = "local_unknown") -> BuildOptionSemantic:
    return BuildOptionSemantic(slot_id=slot_id, sources=(source,))


def parse_qwen_semantic_response(payload: Any, slot_ids: set[str]) -> dict[str, BuildOptionSemantic]:
    """Validate one complete, coordinate-free V2.4D model response."""
    if not isinstance(payload, Mapping) or not isinstance(payload.get("options"), list):
        raise SemanticSchemaError("SEMANTIC_MODEL_SCHEMA_FAIL")
    parsed: dict[str, BuildOptionSemantic] = {}
    for item in payload["options"]:
        if not isinstance(item, Mapping):
            raise SemanticSchemaError("SEMANTIC_MODEL_SCHEMA_FAIL")
        if any(key in item for key in ("bbox", "global_bbox", "click_point", "x", "y")):
            raise SemanticSchemaError("SEMANTIC_MODEL_COORDINATES_REJECTED")
        slot_id = item.get("slot_id")
        if not isinstance(slot_id, str) or slot_id not in slot_ids or slot_id in parsed:
            raise SemanticSchemaError("SEMANTIC_MODEL_SCHEMA_FAIL")
        label = item.get("label")
        if label is not None and (not isinstance(label, str) or not label.strip()):
            raise SemanticSchemaError("SEMANTIC_MODEL_SCHEMA_FAIL")
        locked = item.get("locked")
        if locked is not None and not isinstance(locked, bool):
            raise SemanticSchemaError("SEMANTIC_MODEL_SCHEMA_FAIL")
        costs = item.get("costs", {})
        if not isinstance(costs, Mapping):
            raise SemanticSchemaError("SEMANTIC_MODEL_SCHEMA_FAIL")
        normalized_costs: dict[str, int | float] = {}
        for resource, value in costs.items():
            if not isinstance(resource, str) or resource not in KNOWN_RESOURCES:
                raise SemanticSchemaError("SEMANTIC_MODEL_UNKNOWN_RESOURCE")
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise SemanticSchemaError("SEMANTIC_MODEL_SCHEMA_FAIL")
            if value < 0:
                raise SemanticSchemaError("SEMANTIC_MODEL_NEGATIVE_COST")
            normalized_costs[resource] = value
        confidence = item.get("confidence")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0.0 <= float(confidence) <= 1.0:
            raise SemanticSchemaError("SEMANTIC_MODEL_SCHEMA_FAIL")
        parsed[slot_id] = BuildOptionSemantic(
            slot_id=slot_id,
            label=label.strip() if isinstance(label, str) else None,
            locked=locked,
            costs=normalized_costs,
            confidence=float(confidence),
            sources=("qwen3.8-flash",),
        )
    if set(parsed) != slot_ids:
        raise SemanticSchemaError("SEMANTIC_MODEL_SCHEMA_FAIL")
    return parsed


def merge_semantic(
    geometry: BuildOption,
    local: BuildOptionSemantic,
    model: BuildOptionSemantic | None,
) -> EnrichedBuildOption:
    """Merge semantic sources while preserving deterministic local evidence."""
    if local.slot_id != geometry.id or (model is not None and model.slot_id != geometry.id):
        raise SemanticSchemaError("semantic slot identity does not match geometry")
    if model is None:
        return EnrichedBuildOption(geometry, local)
    diagnostics = dict(model.diagnostics or {})
    locked = model.locked
    sources = list(dict.fromkeys((*local.sources, *model.sources)))
    if local.locked is not None:
        if model.locked is not None and local.locked != model.locked:
            diagnostics["semantic_conflict"] = {"field": "locked", "local": local.locked, "model": model.locked}
        locked = local.locked
    return EnrichedBuildOption(
        geometry,
        replace(model, locked=locked, sources=tuple(sources), diagnostics=diagnostics),
    )


def evaluate_affordability(semantic: BuildOptionSemantic, available: Mapping[str, int | float]) -> BuildAffordability:
    """Evaluate only with complete, non-negative, explicitly known resources."""
    if semantic.locked is not False or not semantic.costs:
        return BuildAffordability(semantic.slot_id, AffordabilityStatus.UNKNOWN, {})
    if any(resource not in KNOWN_RESOURCES for resource in available):
        return BuildAffordability(semantic.slot_id, AffordabilityStatus.UNKNOWN, {})
    for resource, value in available.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            return BuildAffordability(semantic.slot_id, AffordabilityStatus.UNKNOWN, {})
    if any(resource not in available for resource in semantic.costs):
        return BuildAffordability(semantic.slot_id, AffordabilityStatus.UNKNOWN, {})
    shortfall = {
        resource: cost - available[resource]
        for resource, cost in semantic.costs.items()
        if available[resource] < cost
    }
    if shortfall:
        return BuildAffordability(semantic.slot_id, AffordabilityStatus.UNAFFORDABLE, shortfall)
    return BuildAffordability(semantic.slot_id, AffordabilityStatus.AFFORDABLE, {})


def crop_current_card(rgba: bytes, width: int, height: int, bbox: tuple[float, float, float, float] | list[float]) -> tuple[bytes, int, int]:
    """Crop one card using only the current frame's geometry."""
    if len(bbox) != 4 or len(rgba) != width * height * 4:
        raise ValueError("current card crop geometry is invalid")
    left, top, right, bottom = (float(value) for value in bbox)
    x0, y0, x1, y1 = round(left * width), round(top * height), round(right * width), round(bottom * height)
    if not 0 <= x0 < x1 <= width or not 0 <= y0 < y1 <= height:
        raise ValueError("current card bbox is outside frame bounds")
    cropped = b"".join(
        rgba[(row * width + x0) * 4:(row * width + x1) * 4]
        for row in range(y0, y1)
    )
    return cropped, x1 - x0, y1 - y0


def build_card_montage(rgba: bytes, width: int, height: int, options: list[BuildOption]) -> bytes:
    """Build one numbered-by-order montage; no coordinates leave this function."""
    from .capture import encode_rgba_png

    ordered = sorted(options, key=lambda item: item.id)
    cell_width, cell_height, columns = 256, 220, 4
    rows = (len(ordered) + columns - 1) // columns
    canvas = bytearray([238, 231, 207, 255] * (cell_width * columns * cell_height * rows))
    for index, option in enumerate(ordered):
        card, card_width, card_height = crop_current_card(rgba, width, height, option.global_bbox or option.bbox)
        column, row = index % columns, index // columns
        offset_x = column * cell_width + max(0, (cell_width - card_width) // 2)
        offset_y = row * cell_height + max(0, (cell_height - card_height) // 2)
        for card_row in range(card_height):
            target = ((offset_y + card_row) * cell_width * columns + offset_x) * 4
            source = card_row * card_width * 4
            canvas[target:target + card_width * 4] = card[source:source + card_width * 4]
    return encode_rgba_png(cell_width * columns, cell_height * rows, bytes(canvas))


def enrich_options(
    options: list[BuildOption],
    model_semantics: Mapping[str, BuildOptionSemantic] | None = None,
) -> list[EnrichedBuildOption]:
    model_semantics = model_semantics or {}
    return [
        merge_semantic(option, unknown_semantic(option.id), model_semantics.get(option.id))
        for option in options
    ]
