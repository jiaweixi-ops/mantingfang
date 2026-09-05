from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Protocol

from .input import InputCommand
from .models import PlannedAction


class SkillTranslationError(ValueError):
    pass


class InputAdapter(Protocol):
    def execute(self, command: InputCommand) -> dict[str, Any]: ...


@dataclass(frozen=True)
class SkillTranslator:
    """Translate only explicit, schema-checked game skills into input commands."""

    def translate(self, action: PlannedAction) -> list[InputCommand]:
        payload = action.payload
        raw_commands = payload.get("commands")
        if raw_commands is not None:
            if not isinstance(raw_commands, list) or not raw_commands:
                raise SkillTranslationError("commands must be a non-empty list")
            return [self._command(item) for item in raw_commands]
        if action.action_type in {"move", "click", "key_down", "key_up"}:
            return [self._command({"kind": action.action_type, **payload})]
        raise SkillTranslationError(f"unsupported game skill: {action.action_type}")

    def _command(self, raw: Any) -> InputCommand:
        if not isinstance(raw, dict) or not isinstance(raw.get("kind"), str):
            raise SkillTranslationError("each input command requires a kind")
        try:
            return InputCommand(
                kind=raw["kind"],
                x_ratio=raw.get("x_ratio"),
                y_ratio=raw.get("y_ratio"),
                key=raw.get("key"),
            )
        except (TypeError, ValueError) as exc:
            raise SkillTranslationError(str(exc)) from exc


@dataclass
class InputActionExecutor:
    adapter: InputAdapter
    translator: SkillTranslator = SkillTranslator()
    observe_state: Callable[[], dict[str, Any]] | None = None

    def execute(self, action: PlannedAction) -> dict[str, Any]:
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
