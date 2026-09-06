from __future__ import annotations

import pytest

from ai_governor.build_menu import BuildOption
from ai_governor.build_option_semantics import (
    AffordabilityStatus,
    BuildOptionSemantic,
    SemanticSchemaError,
    EnrichedBuildOption,
    evaluate_affordability,
    build_card_montage,
    merge_semantic,
    parse_qwen_semantic_response,
)


def _option(slot_id: str = "build_option_slot_01") -> BuildOption:
    return BuildOption(slot_id, "unknown", (0.20, 0.65, 0.30, 0.78), 0.97, None, {}, (0.20, 0.65, 0.30, 0.78))


def _payload(*items: dict) -> dict:
    return {"options": list(items)}


def _item(slot_id: str = "build_option_slot_01", **extra: object) -> dict:
    return {
        "slot_id": slot_id,
        "label": None,
        "locked": None,
        "costs": {},
        "confidence": 0.88,
        **extra,
    }


def test_semantic_enrichment_preserves_geometry_exactly() -> None:
    option = _option()
    local = BuildOptionSemantic(option.id)
    model = BuildOptionSemantic(option.id, label="民居", confidence=0.94, sources=("qwen3.8-flash",))
    enriched = merge_semantic(option, local, model)
    assert isinstance(enriched, EnrichedBuildOption)
    assert enriched.geometry == option
    assert enriched.semantic.label == "民居"


def test_unknown_semantics_remain_null() -> None:
    semantic = BuildOptionSemantic("build_option_slot_01")
    assert semantic.label is None
    assert semantic.locked is None
    assert semantic.costs == {}


def test_qwen_semantics_require_exact_known_slots_and_reject_coordinates() -> None:
    slots = {"build_option_slot_01", "build_option_slot_02"}
    payload = _payload(_item("build_option_slot_01"), _item("build_option_slot_02", label="民居"))
    result = parse_qwen_semantic_response(payload, slots)
    assert result["build_option_slot_02"].label == "民居"
    with pytest.raises(SemanticSchemaError, match="COORDINATES"):
        parse_qwen_semantic_response(
            _payload(_item("build_option_slot_01", bbox=[0.1, 0.1, 0.2, 0.2]), _item("build_option_slot_02")),
            slots,
        )
    with pytest.raises(SemanticSchemaError, match="SCHEMA"):
        parse_qwen_semantic_response(_payload(_item("build_option_slot_01")), slots)
    with pytest.raises(SemanticSchemaError, match="SCHEMA"):
        parse_qwen_semantic_response(_payload(_item("unknown"), _item("build_option_slot_02")), slots)


def test_negative_or_unknown_costs_are_rejected() -> None:
    with pytest.raises(SemanticSchemaError, match="UNKNOWN_RESOURCE"):
        parse_qwen_semantic_response(
            _payload(_item(costs={"mystery": 10})),
            {"build_option_slot_01"},
        )
    with pytest.raises(SemanticSchemaError, match="NEGATIVE_COST"):
        parse_qwen_semantic_response(
            _payload(_item(costs={"wood": -1})),
            {"build_option_slot_01"},
        )


def test_local_lock_evidence_beats_model_conflict_and_is_recorded() -> None:
    option = _option()
    local = BuildOptionSemantic(option.id, locked=True, confidence=0.96, sources=("local_lock_icon",))
    model = BuildOptionSemantic(option.id, label="民居", locked=False, confidence=0.90, sources=("qwen3.8-flash",))
    enriched = merge_semantic(option, local, model)
    assert enriched.semantic.locked is True
    assert enriched.semantic.diagnostics["semantic_conflict"]["field"] == "locked"


def test_affordability_is_unknown_for_incomplete_costs_or_resources() -> None:
    semantic = BuildOptionSemantic("build_option_slot_01", locked=False, costs={"wood": 20})
    assert evaluate_affordability(semantic, {}) .status is AffordabilityStatus.UNKNOWN
    assert evaluate_affordability(semantic, {"wood": 10}).status is AffordabilityStatus.UNAFFORDABLE
    assert evaluate_affordability(semantic, {"wood": 20}).status is AffordabilityStatus.AFFORDABLE
    unknown_lock = BuildOptionSemantic("build_option_slot_01", locked=None, costs={"wood": 20})
    assert evaluate_affordability(unknown_lock, {"wood": 100}).status is AffordabilityStatus.UNKNOWN


def test_semantic_identity_mismatch_cannot_become_enriched_geometry() -> None:
    with pytest.raises(SemanticSchemaError, match="slot"):
        merge_semantic(_option(), BuildOptionSemantic("different_slot"), None)


def test_card_montage_uses_all_columns_and_preserves_current_geometry_only() -> None:
    width, height = 128, 128
    rgba = bytes((220, 220, 220, 255)) * (width * height)
    options = [
        BuildOption(f"build_option_slot_{index:02d}", "unknown", (0.05, 0.05, 0.20, 0.25), 0.95, None, {}, (0.05, 0.05, 0.20, 0.25))
        for index in range(1, 9)
    ]
    montage = build_card_montage(rgba, width, height, options)
    assert montage.startswith(b"\x89PNG\r\n\x1a\n")
