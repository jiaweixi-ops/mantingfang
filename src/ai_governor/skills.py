from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from .input import InputCommand
from .models import PlannedAction


class SkillTranslationError(ValueError):
    pass


GAME_SKILLS = (
    "OPEN_BUILD_MENU",
    "CLOSE_BUILD_MENU",
    "OPEN_RESIDENTIAL_TAB",
    "OPEN_AGRICULTURE_TAB",
    "OPEN_INDUSTRY_TAB",
    "OPEN_COMMERCIAL_TAB",
    "PAN_CAMERA",
    "ZOOM_IN",
    "ZOOM_OUT",
    "PAUSE_GAME",
    "SET_SPEED_1",
    "SET_SPEED_2",
    "SET_SPEED_3",
    "OPEN_FINANCE",
    "OPEN_TECH",
    "OPEN_POLICY",
    "SAVE_GAME",
    "CANCEL_CURRENT_ACTION",
    "CLOSE_DIALOG",
    "SELECT_EVENT_OPTION",
)


class PreActionValidationError(ValueError):
    """A live action failed validation before any input was emitted."""


def validate_semantic_contract(action: PlannedAction) -> None:
    """Validate the post-action predicate before a live executor is called."""

    expected = action.payload.get("expected_state")
    changed_fields = action.payload.get("changed_fields")
    has_expected = isinstance(expected, dict) and bool(expected)
    has_changed = (
        isinstance(changed_fields, list)
        and bool(changed_fields)
        and all(isinstance(field, str) and field for field in changed_fields)
    )
    if not has_expected and not has_changed:
        raise PreActionValidationError(
            "live action requires a non-empty expected_state or changed_fields predicate"
        )
    if isinstance(expected, dict) and any(not isinstance(key, str) or not key for key in expected):
        raise PreActionValidationError("expected_state keys must be non-empty strings")




class InputAdapter(Protocol):
    def execute(self, command: InputCommand) -> dict[str, Any]: ...


@dataclass(frozen=True)
class SkillTranslator:
    """Translate only explicit, schema-checked game skills into input commands."""

    ui_element_supplier: Callable[[str, str], dict[str, Any] | None] | None = None

    @staticmethod
    def supported_skills() -> tuple[str, ...]:
        return GAME_SKILLS

    def validate_live(self, action: PlannedAction) -> None:
        validate_semantic_contract(action)
        # Translation is deliberately performed during preflight. It validates the
        # complete command sequence before the adapter is allowed to emit input.
        self.translate(action)

    def translate(self, action: PlannedAction) -> list[InputCommand]:
        payload = action.payload
        if action.action_type in GAME_SKILLS:
            # High-level Skills may only resolve through observed UI elements.
            # Raw coordinates/command arrays are reserved for the low-level
            # bridge and are not accepted as a strategic Skill payload.
            return [self._command_from_ui_element(action)]
        raw_commands = payload.get("commands")
        if raw_commands is not None:
            if not isinstance(raw_commands, list) or not raw_commands:
                raise SkillTranslationError("commands must be a non-empty list")
            return [self._command(item) for item in raw_commands]
        if action.action_type in {"move", "click", "key_down", "key_up"}:
            return [self._command({"kind": action.action_type, **payload})]
        raise SkillTranslationError(f"unsupported game skill: {action.action_type}")

    def _command_from_ui_element(self, action: PlannedAction) -> InputCommand:
        target_id = action.payload.get("target_element")
        target_region = action.payload.get("target_region")
        if not isinstance(target_id, str) or not target_id.strip():
            raise SkillTranslationError(
                f"game skill {action.action_type} requires target_element from UI perception"
            )
        if not isinstance(target_region, str) or not target_region.strip():
            raise SkillTranslationError(
                f"game skill {action.action_type} requires target_region from UI perception"
            )
        if self.ui_element_supplier is None:
            raise SkillTranslationError("UI element resolver is not configured")
        element = self.ui_element_supplier(target_region.strip(), target_id.strip())
        if not isinstance(element, dict):
            raise SkillTranslationError(f"UI element not found: {target_id}")
        bbox = element.get("global_bbox")
        if not isinstance(bbox, list) or len(bbox) != 4:
            raise SkillTranslationError(f"UI element has invalid global_bbox: {target_region}/{target_id}")
        left, top, right, bottom = bbox
        try:
            x_ratio = (float(left) + float(right)) / 2
            y_ratio = (float(top) + float(bottom)) / 2
        except (TypeError, ValueError) as exc:
            raise SkillTranslationError(f"UI element bbox is not numeric: {target_id}") from exc
        command_kind = action.payload.get("command_kind", "click")
        return self._command({
            "kind": command_kind,
            "x_ratio": x_ratio,
            "y_ratio": y_ratio,
            "geometry_snapshot": element.get("geometry_snapshot"),
        })

    def _command(self, raw: Any) -> InputCommand:
        if not isinstance(raw, dict) or not isinstance(raw.get("kind"), str):
            raise SkillTranslationError("each input command requires a kind")
        try:
            return InputCommand(
                kind=raw["kind"],
                x_ratio=raw.get("x_ratio"),
                y_ratio=raw.get("y_ratio"),
                key=raw.get("key"),
                geometry_snapshot=raw.get("geometry_snapshot"),
            )
        except (TypeError, ValueError) as exc:
            raise SkillTranslationError(str(exc)) from exc


@dataclass
class InputActionExecutor:
    adapter: InputAdapter
    translator: SkillTranslator = SkillTranslator()
    observe_state: Callable[[], dict[str, Any]] | None = None
    refresh_observation: Callable[[], None] | None = None

    def execute(self, action: PlannedAction) -> dict[str, Any]:
        transaction_factory = getattr(self.adapter, "action_transaction", None)
        transaction = transaction_factory() if callable(transaction_factory) else nullcontext(False)
        with transaction as foreground_reacquired:
            # When the adapter explicitly re-acquired the game foreground, the
            # old UI observation is not a valid click target. Invalidate the
            # capture/vision cache before observing and translating again.
            if foreground_reacquired and self.refresh_observation is not None:
                self.refresh_observation()
            before = self.observe_state() if self.observe_state else None
            commands = self.translator.translate(action)
            results = [self.adapter.execute(command) for command in commands]
            after = self.observe_state() if self.observe_state else None
        simulated = all(result.get("simulated", False) for result in results)
        return {
            "action_type": action.action_type,
            "commands": results,
            "simulated": simulated,
            "before_state": before,
            "after_state": after,
        }
