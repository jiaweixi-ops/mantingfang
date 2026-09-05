from __future__ import annotations

from dataclasses import dataclass

from .models import utc_now
from .storage import SQLiteStore


@dataclass
class Watchdog:
    store: SQLiteStore

    def heartbeat(self) -> None:
        self.store.set_runtime("last_heartbeat", utc_now())

    def pause(self, reason: str = "manual pause") -> None:
        self.store.set_runtime("paused", True)
        self.store.audit("watchdog", "governor paused", {"reason": reason})

    def resume(self) -> None:
        self.store.set_runtime("paused", False)
        self.store.set_runtime("recovery_required", False)
        self.store.audit("watchdog", "governor resumed", {})

    def require_recovery(self, reason: str) -> None:
        self.store.set_runtime("recovery_required", True)
        self.store.set_runtime("paused", True)
        self.store.audit("watchdog", "manual recovery required", {"reason": reason})
