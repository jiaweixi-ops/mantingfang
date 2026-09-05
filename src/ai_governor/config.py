from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


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
    game_window_title: str = "满庭芳：宋上繁华"
    deepseek_api_base: str = "https://api.deepseek.com"
    deepseek_api_key: str | None = None
    deepseek_vision_model: str | None = None
    deepseek_reasoning_model: str | None = None
    feishu_app_id: str | None = None
    feishu_app_secret: str | None = None
    feishu_verification_token: str | None = None
    feishu_encrypt_key: str | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        mode = os.getenv("GOVERNOR_EXECUTION_MODE", "dry-run").strip().lower()
        if mode not in {"dry-run", "live"}:
            raise ValueError("GOVERNOR_EXECUTION_MODE must be 'dry-run' or 'live'")
        return cls(
            db_path=Path(os.getenv("GOVERNOR_DB_PATH", "data/governor.db")),
            memory_profile_path=Path(os.environ["GOVERNOR_MEMORY_PROFILE"]) if os.getenv("GOVERNOR_MEMORY_PROFILE") else None,
            execution_mode=mode,
            allow_critical_actions=_bool_env("GOVERNOR_ALLOW_CRITICAL_ACTIONS"),
            game_window_title=os.getenv("GOVERNOR_GAME_WINDOW_TITLE", cls.game_window_title),
            deepseek_api_base=os.getenv("DEEPSEEK_API_BASE", cls.deepseek_api_base).rstrip("/"),
            deepseek_api_key=os.getenv("DEEPSEEK_API_KEY") or None,
            deepseek_vision_model=os.getenv("DEEPSEEK_VISION_MODEL") or None,
            deepseek_reasoning_model=os.getenv("DEEPSEEK_REASONING_MODEL") or None,
            feishu_app_id=os.getenv("FEISHU_APP_ID") or None,
            feishu_app_secret=os.getenv("FEISHU_APP_SECRET") or None,
            feishu_verification_token=os.getenv("FEISHU_VERIFICATION_TOKEN") or None,
            feishu_encrypt_key=os.getenv("FEISHU_ENCRYPT_KEY") or None,
        )

    def ensure_directories(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
