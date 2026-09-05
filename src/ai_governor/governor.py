from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol

from .actions import ActionEngine
from .models import ActionPlan, Observation
from .storage import SQLiteStore
from .state import CanonicalGameState, StateAggregator
from .skills import GAME_SKILLS
from .watchdog import Watchdog


class StrategyBrain(Protocol):
    def complete_json(self, messages: list[dict[str, Any]], *, model: str | None = None, temperature: float = 0) -> dict[str, Any]: ...


@dataclass
class Governor:
    """One safe observe -> decide -> execute cycle.

    The class deliberately does not own a timer or a window injector. A host
    process can schedule cycles after it has established that the game window
    is the intended target.
    """

    store: SQLiteStore
    brain: StrategyBrain
    actions: ActionEngine
    watchdog: Watchdog
    model: str | None = None
    state_aggregator: StateAggregator = field(default_factory=StateAggregator)

    def run_cycle(self, observation: Observation) -> dict[str, Any]:
        return self.run_observations([observation])

    def run_observations(self, observations: list[Observation]) -> dict[str, Any]:
        if not observations:
            raise ValueError("at least one observation is required")
        for observation in observations:
            self.store.add_observation(observation)
        state = self.state_aggregator.aggregate(observations)
        self.watchdog.heartbeat()
        if self.store.get_runtime("paused", False) or self.store.get_runtime("recovery_required", False):
            return {"status": "blocked", "reason": "paused or recovery required"}
        try:
            response = self.brain.complete_json(self._messages(state), model=self.model)
            plan = ActionPlan.from_dict(response)
        except Exception as exc:  # noqa: BLE001 — invalid AI output must halt safely
            self.watchdog.require_recovery(f"invalid strategy response: {exc}")
            return {"status": "needs_recovery", "error": str(exc)}
        results = self.actions.execute_plan(plan)
        return {"status": "executed", "plan": plan.to_dict(), "results": results}

    def _messages(self, state: CanonicalGameState) -> list[dict[str, Any]]:
        goals = self.store.active_goals()
        return [
            {
                "role": "system",
                "content": (
                    "你是《满庭芳：宋上繁华》的唯一 DeepSeek 城市治理大脑。"
                    "只根据已观测事实和当前目标生成 JSON action plan；不要编造看不到的状态。"
                    "高风险剧情、战争、不可逆政策使用 critical，程序会阻止它们。"
                    "可用游戏 Skill 只有："
                    f"{', '.join(GAME_SKILLS)}。"
                    "动作必须使用 action_type=Skill 名称，并携带由视觉 UI 边界框校准出的 commands；"
                    "不要猜测坐标。每个 live 动作必须同时提供非空 expected_state 或 changed_fields，"
                    "否则会在发送鼠标键盘前被阻止。"
                ),
            },
            {
                "role": "user",
                "content": json.dumps({
                    "canonical_game_state": state.to_dict(),
                    "active_goals": goals,
                    "required_schema": {
                        "reason": "string",
                        "actions": [{"action_type": "string", "payload": "object", "risk": "info|safe|important|critical"}],
                    },
                }, ensure_ascii=False),
            },
        ]
