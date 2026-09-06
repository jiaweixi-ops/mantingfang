from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from zoneinfo import ZoneInfo

from .storage import SQLiteStore


@dataclass
class ReportService:
    store: SQLiteStore

    @staticmethod
    def _values(data: dict) -> dict:
        nested = data.get("values")
        return nested if isinstance(nested, dict) else data

    def _state_delta(self) -> dict[str, str]:
        observations = self.store.recent_observations(30)
        if len(observations) < 2:
            return {}
        latest = self._values(observations[0]["data"])
        previous = self._values(observations[1]["data"])
        delta: dict[str, str] = {}
        for key in ("population", "money", "food", "wood", "stone", "happiness", "labor"):
            before, after = previous.get(key), latest.get(key)
            if isinstance(before, (int, float)) and isinstance(after, (int, float)) and before != after:
                sign = "+" if after - before > 0 else ""
                delta[key] = f"{before} → {after} ({sign}{after - before:g})"
        return delta

    def status(self) -> str:
        observation = self.store.latest_observation()
        state = observation["data"] if observation else {}
        goals = self.store.active_goals()
        paused = self.store.get_runtime("paused", False)
        recovery = self.store.get_runtime("recovery_required", False)
        lines = [
            "《满庭芳》AI Governor 当前状态",
            f"运行状态：{'已暂停' if paused else '运行中（{0}）'.format('需恢复确认' if recovery else 'dry-run')} ",
            f"今日动作记录：{self.store.today_action_count()}",
            f"Qwen Token：{self.store.today_token_usage()['total_tokens']}",
            f"最新观测区域：{observation.get('region', '无') if observation else '无'}",
        ]
        if state:
            lines.append("观测数据：" + ", ".join(f"{k}={v}" for k, v in state.items() if k != "confidence"))
        lines.append(f"当前目标：{goals[0]['title'] if goals else '尚未设置'}")
        return "\n".join(lines)

    def goals(self) -> str:
        goals = self.store.active_goals()
        if not goals:
            return "当前没有 active 目标。"
        return "\n".join(["当前阶段目标："] + [f"- [{goal['level']}] {goal['title']}" for goal in goals])

    def daily_report(self) -> str:
        today = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")
        observation = self.store.latest_observation()
        events = self.store.recent_events(5)
        actions = self.store.today_actions()
        usage = self.store.today_token_usage()
        delta = self._state_delta()
        latest_state = self._values(observation["data"]) if observation else {}
        bottlenecks = [name for name in ("food", "wood", "stone", "money") if isinstance(latest_state.get(name), (int, float)) and latest_state[name] < 0]
        action_lines = [f"- {item['action_type']}：{json.dumps(item['payload'], ensure_ascii=False)}" for item in actions[:10]]
        delta_lines = [f"- {key}：{value}" for key, value in delta.items()] or ["- 暂无足够历史观测"]
        return "\n".join([
            f"《满庭芳》AI 城市日报｜{today}",
            "",
            "今天完成了什么：",
            f"今日动作记录：{self.store.today_action_count()}",
            *(action_lines or ["- 暂无已记录动作"]),
            "",
            "城市状态变化：",
            *delta_lines,
            "",
            f"当前城市状态：{latest_state or '暂无观测'}",
            f"当前瓶颈：{', '.join(bottlenecks) if bottlenecks else '暂无规则可确认的负库存瓶颈'}",
            f"下一阶段目标：{self.store.active_goals()[0]['title'] if self.store.active_goals() else '尚未设置'}",
            f"Qwen 用量：prompt={usage['prompt_tokens']}，completion={usage['completion_tokens']}，total={usage['total_tokens']}",
            "",
            "最近重大事件：",
            *([f"- {event['title']}：{event['body']}" for event in events] or ["- 暂无"]),
            "",
            "说明：日报按需生成；重大事件由网关主动通知。",
        ])
