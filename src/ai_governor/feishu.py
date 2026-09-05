from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .models import Goal, MajorEvent
from .reporting import ReportService
from .storage import SQLiteStore
from .watchdog import Watchdog


class FeishuTransport(Protocol):
    def send_text(self, text: str) -> None: ...


class NullFeishuTransport:
    def __init__(self) -> None:
        self.sent: list[str] = []

    def send_text(self, text: str) -> None:
        self.sent.append(text)


@dataclass
class CommandRouter:
    store: SQLiteStore
    reports: ReportService
    watchdog: Watchdog

    def handle(self, text: str) -> str:
        command = " ".join(text.strip().split())
        if command in {"获取日报", "日报", "今天怎么样", "今天干了什么"}:
            return self.reports.daily_report()
        if command in {"当前状态", "状态", "现在怎么样"}:
            return self.reports.status()
        if command in {"当前目标", "目标", "下一步"}:
            return self.reports.goals()
        if command == "暂停托管":
            self.watchdog.pause("Feishu command")
            return "已暂停托管；恢复前不会执行动作。"
        if command == "继续托管":
            self.watchdog.resume()
            return "已恢复托管；当前仍处于 dry-run，真实输入注入未启用。"
        if command.startswith("修改目标 "):
            title = command.removeprefix("修改目标 ").strip()
            if not title:
                return "用法：修改目标 人口达到2000且财政保持正增长"
            self.store.replace_active_long_term_goal(Goal(title=title, level="long-term"))
            return f"已记录新长期目标：{title}"
        return "可用命令：获取日报、当前状态、当前目标、暂停托管、继续托管、修改目标 <内容>"


@dataclass
class FeishuGateway:
    router: CommandRouter
    transport: FeishuTransport

    def on_text_message(self, text: str) -> str:
        response = self.router.handle(text)
        self.transport.send_text(response)
        return response

    def notify_major_event(self, event: MajorEvent) -> str:
        self.router.store.add_event(event)
        if event.requires_decision:
            self.router.watchdog.pause("major event requires user decision")
        prefix = "🔴" if event.requires_decision else ("🟡" if event.severity.value == "important" else "🟢")
        text = f"{prefix} {event.title}\n{event.body}"
        if event.requires_decision:
            text += "\n\n系统已暂停，等待你的明确决策。"
        self.transport.send_text(text)
        return text
