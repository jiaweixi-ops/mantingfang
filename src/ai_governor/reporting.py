from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .storage import SQLiteStore


@dataclass
class ReportService:
    store: SQLiteStore

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
        today = datetime.now().strftime("%Y-%m-%d")
        observation = self.store.latest_observation()
        events = self.store.recent_events(5)
        return "\n".join([
            f"《满庭芳》AI 城市日报｜{today}",
            "",
            f"今日动作记录：{self.store.today_action_count()}",
            f"最新城市状态：{observation['data'] if observation else '暂无视觉观测'}",
            f"下一阶段目标：{self.store.active_goals()[0]['title'] if self.store.active_goals() else '尚未设置'}",
            "",
            "最近重大事件：",
            *([f"- {event['title']}：{event['body']}" for event in events] or ["- 暂无"]),
            "",
            "说明：日报按需生成；重大事件由网关主动通知。",
        ])
