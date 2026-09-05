from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .models import Goal, MajorEvent
from .reporting import ReportService
from .storage import SQLiteStore
from .watchdog import Watchdog


class FeishuTransport(Protocol):
    def send_text(self, text: str) -> None: ...
    def send_image(self, image_path: str) -> None: ...


class NullFeishuTransport:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self.sent_images: list[str] = []

    def send_text(self, text: str) -> None:
        self.sent.append(text)

    def send_image(self, image_path: str) -> None:
        self.sent_images.append(image_path)


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
            pending = self.store.get_runtime("pending_decision")
            if isinstance(pending, dict) and pending.get("status") == "pending":
                return "当前仍有待决重大事件；请回复‘选择方案 <内容>’或‘交给AI’。"
            self.watchdog.resume()
            return "已恢复托管；当前仍处于 dry-run，真实输入注入未启用。"
        if command.startswith("选择方案 ") or command == "交给AI":
            pending = self.store.get_runtime("pending_decision")
            if not isinstance(pending, dict) or pending.get("status") != "pending":
                return "当前没有等待决策的重大事件。"
            decision = "AI" if command == "交给AI" else command.removeprefix("选择方案 ").strip()
            if not decision:
                return "用法：选择方案 方案一；或回复：交给AI"
            resolved = {**pending, "status": "resolved", "decision": decision}
            self.store.set_runtime("pending_decision", resolved)
            self.store.set_runtime("last_decision", resolved)
            self.watchdog.resume()
            return f"已记录重大事件决策：{decision}；托管已恢复。"
        if command.startswith("修改目标 "):
            title = command.removeprefix("修改目标 ").strip()
            if not title:
                return "用法：修改目标 人口达到2000且财政保持正增长"
            self.store.replace_active_long_term_goal(Goal(title=title, level="long-term"))
            return f"已记录新长期目标：{title}"
        return "可用命令：获取日报、当前状态、当前目标、暂停托管、继续托管、选择方案 <内容>、交给AI、修改目标 <内容>"


@dataclass
class FeishuGateway:
    router: CommandRouter
    transport: FeishuTransport
    record_event: bool = True

    def on_text_message(self, text: str) -> str:
        response = self.router.handle(text)
        self.transport.send_text(response)
        return response

    def notify_major_event(self, event: MajorEvent) -> str:
        if self.record_event:
            self.router.store.add_event(event)
        if event.requires_decision:
            if not self.router.store.get_runtime("paused", False):
                self.router.watchdog.pause("major event requires user decision")
            self.router.store.set_runtime(
                "pending_decision",
                {"event_id": event.id, "title": event.title, "status": "pending"},
            )
        prefix = "🔴" if event.requires_decision else ("🟡" if event.severity.value == "important" else "🟢")
        text = f"{prefix} {event.title}\n{event.body}"
        if event.requires_decision:
            text += "\n\n系统已暂停，等待你的明确决策。"
        if event.screenshot_path:
            send_image = getattr(self.transport, "send_image", None)
            if callable(send_image):
                try:
                    send_image(event.screenshot_path)
                except Exception as exc:  # noqa: BLE001 — text notification must survive image failure
                    self.router.store.audit("feishu", "event screenshot delivery failed", {"event_id": event.id, "error": str(exc)})
                    text += f"\n\n截图发送失败：{exc}"
            else:
                text += "\n\n当前飞书传输未启用截图上传。"
        self.transport.send_text(text)
        return text
