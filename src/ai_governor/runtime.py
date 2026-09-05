from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .actions import ActionEngine, DryRunExecutor
from .capture import ClientAreaCapture, Win32ClientCaptureBackend
from .config import Settings
from .deepseek import DeepSeekClient, DeepSeekConfigurationError
from .governor import Governor
from .input import Win32SendInputBackend, WindowsSendInputAdapter
from .loop import CompositeObservationSource, GovernorLoop
from .memory import MemoryProfile, MemorySampler, WindowsMemoryBackend, WindowsProcessEnumerator
from .perception import PerceptionEngine, RegionCatalog
from .skills import InputActionExecutor
from .state import StateAggregator
from .storage import SQLiteStore
from .verification import SemanticStateVerifier
from .watchdog import Watchdog
from .window import SteamWindowAdapter, Win32WindowBackend


class RuntimeConfigurationError(RuntimeError):
    pass


@dataclass
class SteamVisionObservationSource:
    capture: ClientAreaCapture
    perception: PerceptionEngine
    regions: tuple[str, ...] = ("resources", "map", "events")

    def observe(self):
        frame = self.capture.capture()
        return [
            self.perception.observe_rgba(frame.rgba, frame.width, frame.height, region, context="Governor 运行时状态采集")
            for region in self.regions
        ]


@dataclass
class MemoryObservationSource:
    sampler: MemorySampler

    def observe(self):
        return self.sampler.observe()


@dataclass
class GovernorRuntime:
    loop: GovernorLoop
    source: CompositeObservationSource
    governor: Governor


def build_runtime(settings: Settings, store: SQLiteStore, regions: Iterable[str] = ("resources", "map", "events")) -> GovernorRuntime:
    if not settings.deepseek_api_key:
        raise DeepSeekConfigurationError("DEEPSEEK_API_KEY is not configured; run requires a real DeepSeek endpoint")
    if not settings.deepseek_reasoning_model:
        raise DeepSeekConfigurationError("DEEPSEEK_REASONING_MODEL is not configured")
    if not settings.deepseek_vision_model:
        raise DeepSeekConfigurationError("DEEPSEEK_VISION_MODEL is not configured")
    client = DeepSeekClient(
        settings.deepseek_api_base,
        settings.deepseek_api_key,
        settings.deepseek_reasoning_model,
        usage_callback=store.record_token_usage,
    )
    window = SteamWindowAdapter(settings.game_window_title, Win32WindowBackend())
    capture = ClientAreaCapture(window, Win32ClientCaptureBackend())
    perception = PerceptionEngine(client, RegionCatalog(), model=settings.deepseek_vision_model)
    vision_source = SteamVisionObservationSource(capture, perception, tuple(regions))
    sources = [vision_source]
    if settings.memory_profile_path is not None:
        profile = MemoryProfile.from_json(settings.memory_profile_path)
        sources.append(MemoryObservationSource(MemorySampler(profile, WindowsProcessEnumerator(), WindowsMemoryBackend())))
    source = CompositeObservationSource(tuple(sources))
    aggregator = StateAggregator()

    def observe_state() -> dict:
        return aggregator.aggregate(source.observe()).to_dict()["values"]

    if settings.execution_mode == "dry-run":
        executor = DryRunExecutor()
        verifier = None
    else:
        adapter = WindowsSendInputAdapter(
            window,
            Win32SendInputBackend(),
            enabled=True,
            allow_clicks=True,
            allow_keyboard=True,
        )
        executor = InputActionExecutor(adapter, observe_state=observe_state)
        verifier = SemanticStateVerifier(observe_state)
    watchdog = Watchdog(store)
    actions = ActionEngine(settings, store, executor, verifier)
    governor = Governor(store, client, actions, watchdog, model=settings.deepseek_reasoning_model, state_aggregator=aggregator)
    loop = GovernorLoop(source, governor, store, watchdog)
    return GovernorRuntime(loop=loop, source=source, governor=governor)
