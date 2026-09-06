"""Read-only V2.4D semantic parsing against one fresh CATEGORY_OPEN frame."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from .build_menu import BuildMenuState
from .build_menu_observer import build_local_menu_snapshot
from .build_option_semantics import (
    BuildOptionSemantic,
    SemanticSchemaError,
    build_card_montage,
    enrich_options,
    parse_qwen_semantic_response,
    unknown_semantic,
)
from .capture import CaptureError, ClientAreaCapture, WindowsGraphicsCaptureBackend
from .config import Settings
from .qwen import QwenClient, QwenConfigurationError, QwenRequestError
from .perception import RegionCatalog
from .storage import SQLiteStore
from .window import SteamWindowAdapter, Win32WindowBackend, WindowError, WindowNotFound


class BuildOptionSemanticError(RuntimeError):
    """Raised when a read-only V2.4D sample cannot be completed safely."""


def _locate_window(settings: Settings, backend: Win32WindowBackend, title: str | None) -> SteamWindowAdapter:
    selected = title or settings.game_window_title
    window = SteamWindowAdapter(selected, backend)
    try:
        window.locate()
    except WindowNotFound:
        if title or selected == "Song":
            raise
        window = SteamWindowAdapter("Song", backend)
        window.locate()
    return window


def _semantic_prompt(slot_ids: list[str]) -> str:
    slots = ", ".join(slot_ids)
    return (
        "你正在读取《满庭芳：宋上繁华》当前建筑分类页面的建筑卡片拼图。"
        "图片按输入顺序从左到右、从上到下排列，输入槽位为：" + slots + "。"
        "只返回一个 JSON object，最外层必须是 object，不能是 array。"
        "严格返回 {\"options\":[{\"slot_id\":\"...\",\"label\":\"建筑名称或 null\","
        "\"locked\":true|false|null,\"costs\":{\"gold\":0,\"rice\":0,\"vegetable\":0,\"wood\":0,\"stone\":0},\"confidence\":0.0}]}。"
        "必须恰好返回每个输入槽位一次；label 不确定就 null；locked 不确定就 null；"
        "只在资源类型和数量同时清晰可见时写 costs，否则写空对象。"
        "资源键只能是 gold、rice、vegetable、wood、stone。"
        "严禁输出 bbox、global_bbox、click_point、x、y 或任何坐标字段。不要解释，不要猜测。"
    )


def _empty_report() -> dict[str, Any]:
    return {
        "phase": "V2.4D",
        "state": "unknown",
        "options_detected": 0,
        "options": [],
        "real_labels_resolved": 0,
        "lock_states_resolved": 0,
        "costs_resolved": 0,
        "qwen_flash_calls": 0,
        "qwen_max_calls": 0,
        "sendinput_calls": 0,
        "mouse": 0,
        "keyboard": 0,
        "map_clicks": 0,
        "building_option_clicks": 0,
        "save_writes": 0,
        "memory_writes": 0,
        "runtime_telemetry": False,
        "mono_debugger": False,
        "result": "FAIL",
    }


def run_read_only_build_option_semantics(
    settings: Settings,
    store: SQLiteStore,
    *,
    output_dir: Path = Path("data/probe/V2.4D"),
    window_title: str | None = None,
) -> dict[str, Any]:
    """Capture and enrich current Build Options without any input side effect."""
    output_dir.mkdir(parents=True, exist_ok=True)
    report = _empty_report()
    try:
        backend = Win32WindowBackend()
        window = _locate_window(settings, backend, window_title)
        capture = ClientAreaCapture(window, WindowsGraphicsCaptureBackend(), reject_near_black=True)
        catalog = RegionCatalog()
        frame = capture.capture()
        snapshot = build_local_menu_snapshot(
            phase="category",
            frame=frame,
            capture=capture,
            backend=backend,
            catalog=catalog,
        )
        if snapshot.state is not BuildMenuState.CATEGORY_OPEN:
            raise BuildOptionSemanticError(f"V2.4D requires CATEGORY_OPEN, got {snapshot.state.value}")
        if snapshot.geometry is None or snapshot.close_control is None or snapshot.close_control.get("confidence", 0.0) < 0.90:
            raise BuildOptionSemanticError("V2.4D requires a fresh local close control at confidence >= 0.90")
        if not snapshot.options:
            raise BuildOptionSemanticError("V2.4D found no current-frame BUILD_OPTION slots")
        frame_id = uuid4().hex
        slot_ids = [option.id for option in snapshot.options]
        local = {option.id: unknown_semantic(option.id) for option in snapshot.options}
        model: dict[str, BuildOptionSemantic] = {}
        qwen_error: str | None = None
        if not any(item.label for item in local.values()):
            if not settings.qwen_api_key:
                qwen_error = "QWEN_API_KEY is not configured"
            else:
                montage = build_card_montage(frame.rgba, frame.width, frame.height, list(snapshot.options))
                report["qwen_flash_calls"] = 1
                client = QwenClient(
                    settings.qwen_api_base,
                    settings.qwen_api_key,
                    default_model="qwen3.8-flash",
                    max_retries=0,
                    backoff_seconds=0,
                    usage_callback=store.record_token_usage,
                )
                try:
                    raw = client.analyze_image_json(
                        montage,
                        _semantic_prompt(slot_ids),
                        model="qwen3.8-flash",
                    )
                    model = parse_qwen_semantic_response(raw, set(slot_ids))
                except (SemanticSchemaError, QwenConfigurationError, QwenRequestError, ValueError) as exc:
                    qwen_error = str(exc)
                    model = {}
        enriched = enrich_options(list(snapshot.options), model)
        report.update({
            "state": snapshot.state.value,
            "frame_id": frame_id,
            "geometry": snapshot.geometry.to_dict(),
            "hwnd": snapshot.geometry.hwnd,
            "pid": snapshot.geometry.pid,
            "capture": frame.diagnostic.to_dict() if frame.diagnostic else None,
            "close_control": snapshot.close_control,
            "options_detected": len(enriched),
            "options": [item.to_dict() for item in enriched],
        })
        report["real_labels_resolved"] = sum(1 for item in enriched if item.semantic.label)
        report["lock_states_resolved"] = sum(1 for item in enriched if item.semantic.locked is not None)
        report["costs_resolved"] = sum(1 for item in enriched if item.semantic.costs)
        if qwen_error:
            report["semantic_failure"] = qwen_error
        if report["real_labels_resolved"] >= 1:
            report["result"] = (
                "PASS_SEMANTIC_CALIBRATED"
                if report["lock_states_resolved"] >= 1 and report["costs_resolved"] >= 1
                else "PASS_SEMANTIC_MINIMUM"
            )
        else:
            report["failure_class"] = "SEMANTIC_UNRESOLVED"
            report["failure_reason"] = qwen_error or "no real labels were resolved"
    except (BuildOptionSemanticError, CaptureError, WindowError, OSError, ValueError) as exc:
        report["failure_class"] = type(exc).__name__
        report["failure_reason"] = str(exc)
    except Exception as exc:  # noqa: BLE001 - read-only evidence must still be persisted.
        report["failure_class"] = type(exc).__name__
        report["failure_reason"] = str(exc)
    finally:
        (output_dir / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report
