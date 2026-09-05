from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable

from .loop import GovernorLoop, LoopCycle
from .storage import SQLiteStore
from .watchdog import Watchdog


@dataclass
class GovernorSupervisor:
    """Restart orchestration after unexpected loop exceptions, never after a safety halt."""

    loop_factory: Callable[[], GovernorLoop]
    store: SQLiteStore
    watchdog: Watchdog
    max_restarts: int = 3
    backoff_seconds: float = 5.0
    sleep_fn: Callable[[float], None] = time.sleep

    def run(self, *, max_cycles: int | None = None, stop_event: threading.Event | None = None) -> list[LoopCycle]:
        if self.max_restarts < 0:
            raise ValueError("max_restarts must be non-negative")
        if self.backoff_seconds < 0:
            raise ValueError("backoff_seconds must be non-negative")
        stop = stop_event or threading.Event()
        cycles: list[LoopCycle] = []
        restarts = 0
        while not stop.is_set() and (max_cycles is None or len(cycles) < max_cycles):
            remaining = None if max_cycles is None else max_cycles - len(cycles)
            try:
                result = self.loop_factory().run(max_cycles=remaining, stop_event=stop)
                cycles.extend(result)
                if not result:
                    break
                last = result[-1]
                if last.status == "needs_recovery" or self.store.get_runtime("recovery_required", False) or self.store.get_runtime("paused", False):
                    break
                if max_cycles is not None and len(cycles) >= max_cycles:
                    break
            except Exception as exc:  # noqa: BLE001 — supervisor must record and bound restarts
                restarts += 1
                self.store.audit("supervisor", "loop crashed; restart scheduled", {"error": str(exc), "restart": restarts})
                if restarts > self.max_restarts:
                    self.watchdog.require_recovery("supervisor restart limit exceeded")
                    break
                self.sleep_fn(self.backoff_seconds * (2 ** (restarts - 1)))
        return cycles
