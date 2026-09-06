from __future__ import annotations

import os
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PERSISTED_SETTINGS_KEYS = (
    "qwen_api_base",
    "qwen_api_key",
    "qwen_vision_model",
    "qwen_reasoning_model",
)


def user_settings_path() -> Path:
    """Return the per-user settings path; secrets never live in the repository."""
    configured = os.getenv("GOVERNOR_SETTINGS_PATH")
    if configured:
        return Path(configured)
    local_app_data = os.getenv("LOCALAPPDATA")
    base = Path(local_app_data) if local_app_data else Path.home() / ".local" / "share"
    return base / "MantingfangAIGovernor" / "settings.json"


def load_persisted_settings(path: Path | None = None) -> dict[str, str]:
    settings_path = path or user_settings_path()
    try:
        raw = json.loads(settings_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {
        key: value.strip()
        for key in PERSISTED_SETTINGS_KEYS
        if isinstance(value := raw.get(key), str) and value.strip()
    }


def save_persisted_settings(values: dict[str, Any], path: Path | None = None) -> Path:
    """Atomically save provider settings outside the repository."""
    settings_path = path or user_settings_path()
    payload: dict[str, str] = {}
    for key in PERSISTED_SETTINGS_KEYS:
        value = values.get(key)
        if isinstance(value, str) and value.strip():
            payload[key] = value.strip()
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix="settings-", suffix=".tmp", dir=settings_path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary_name, settings_path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
    return settings_path


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "是"}


@dataclass(frozen=True)
class Settings:
    db_path: Path = Path("data/governor.db")
    memory_profile_path: Path | None = None
    execution_mode: str = "dry-run"
    allow_critical_actions: bool = False
    allow_live_input: bool = False
    game_window_title: str = "满庭芳：宋上繁华"
    qwen_api_base: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    qwen_api_key: str | None = None
    qwen_vision_model: str | None = None
    qwen_reasoning_model: str | None = None
    runtime_bridge_url: str = "http://127.0.0.1:18765"
    runtime_telemetry_enabled: bool = False
    runtime_game_version: str | None = None
    auto_foreground: bool = False
    restore_previous_foreground: bool = True
    foreground_stable_seconds: float = 0.6
    foreground_timeout_seconds: float = 5.0
    feishu_app_id: str | None = None
    feishu_app_secret: str | None = None
    feishu_verification_token: str | None = None
    feishu_encrypt_key: str | None = None
    feishu_api_base: str = "https://open.feishu.cn"
    feishu_target_chat_id: str | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        persisted = load_persisted_settings()

        def configured(name: str, key: str, default: str | None = None) -> str | None:
            return os.getenv(name) or persisted.get(key) or default

        mode = os.getenv("GOVERNOR_EXECUTION_MODE", "dry-run").strip().lower()
        if mode not in {"dry-run", "live"}:
            raise ValueError("GOVERNOR_EXECUTION_MODE must be 'dry-run' or 'live'")
        runtime_telemetry_enabled = _bool_env("GOVERNOR_RUNTIME_TELEMETRY")
        runtime_game_version = os.getenv("GOVERNOR_RUNTIME_GAME_VERSION") or None
        if runtime_telemetry_enabled and not runtime_game_version:
            raise ValueError("GOVERNOR_RUNTIME_GAME_VERSION is required when GOVERNOR_RUNTIME_TELEMETRY=true")
        return cls(
            db_path=Path(os.getenv("GOVERNOR_DB_PATH", "data/governor.db")),
            memory_profile_path=Path(os.environ["GOVERNOR_MEMORY_PROFILE"]) if os.getenv("GOVERNOR_MEMORY_PROFILE") else None,
            execution_mode=mode,
            allow_critical_actions=_bool_env("GOVERNOR_ALLOW_CRITICAL_ACTIONS"),
            allow_live_input=_bool_env("GOVERNOR_ALLOW_LIVE_INPUT"),
            game_window_title=os.getenv("GOVERNOR_GAME_WINDOW_TITLE", cls.game_window_title),
            qwen_api_base=(configured("QWEN_API_BASE", "qwen_api_base", cls.qwen_api_base) or cls.qwen_api_base).rstrip("/"),
            qwen_api_key=configured("QWEN_API_KEY", "qwen_api_key"),
            qwen_vision_model=configured("QWEN_VISION_MODEL", "qwen_vision_model"),
            qwen_reasoning_model=configured("QWEN_REASONING_MODEL", "qwen_reasoning_model"),
            runtime_bridge_url=os.getenv("GOVERNOR_RUNTIME_BRIDGE_URL", cls.runtime_bridge_url).rstrip("/"),
            runtime_telemetry_enabled=runtime_telemetry_enabled,
            runtime_game_version=runtime_game_version,
            auto_foreground=_bool_env("GOVERNOR_AUTO_FOREGROUND"),
            restore_previous_foreground=_bool_env("GOVERNOR_RESTORE_PREVIOUS_FOREGROUND", True),
            foreground_stable_seconds=float(os.getenv("GOVERNOR_FOREGROUND_STABLE_SECONDS", "0.6")),
            foreground_timeout_seconds=float(os.getenv("GOVERNOR_FOREGROUND_TIMEOUT_SECONDS", "5.0")),
            feishu_app_id=os.getenv("FEISHU_APP_ID") or None,
            feishu_app_secret=os.getenv("FEISHU_APP_SECRET") or None,
            feishu_verification_token=os.getenv("FEISHU_VERIFICATION_TOKEN") or None,
            feishu_encrypt_key=os.getenv("FEISHU_ENCRYPT_KEY") or None,
            feishu_api_base=os.getenv("FEISHU_API_BASE", cls.feishu_api_base).rstrip("/"),
            feishu_target_chat_id=os.getenv("FEISHU_TARGET_CHAT_ID") or None,
        )

    def ensure_directories(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
