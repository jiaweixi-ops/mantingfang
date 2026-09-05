from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Callable, Iterable

from .actions import ActionEngine, DryRunExecutor
from .capture import ClientAreaCapture, Win32ClientCaptureBackend
from .config import Settings
from .deepseek import DeepSeekClient, DeepSeekConfigurationError
from .governor import Governor
from .input import Win32SendInputBackend, WindowsSendInputAdapter
from .loop import CompositeObservationSource, GovernorLoop
from .memory import MemoryProfile, MemorySampler, WindowsMemoryBackend, WindowsProcessEnumerator
from .perception import PerceptionEngine, RegionCatalog
from .skills import InputActionExecutor, SkillTranslator
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
    force_refresh_seconds: float = 60.0
    clock: Callable[[], float] = time.monotonic
    _cache: dict[str, tuple[str, float, object]] = field(default_factory=dict, init=False, repr=False)
    last_changed_regions: tuple[str, ...] = field(default_factory=tuple, init=False)

    def observe(self):
        frame = self.capture.capture()
        now = self.clock()
        observations = []
        changed: list[str] = []
        for region_name in self.regions:
            digest = self._region_digest(frame.rgba, frame.width, frame.height, region_name)
            cached = self._cache.get(region_name)
            if cached is not None:
                cached_digest, analyzed_at, observation = cached
                if digest == cached_digest and now - analyzed_at < self.force_refresh_seconds:
                    observations.append(observation)
                    continue
            observation = self.perception.observe_rgba(
                frame.rgba,
                frame.width,
                frame.height,
                region_name,
                context="Governor 运行时状态采集",
            )
            self._cache[region_name] = (digest, now, observation)
            observations.append(observation)
            changed.append(region_name)
        self.last_changed_regions = tuple(changed)
        return observations

    def _region_digest(self, rgba: bytes, width: int, height: int, region_name: str) -> str:
        left, top, right, bottom = self.perception.regions.get(region_name).crop_box(width, height)
        digest = hashlib.sha256()
        for row in range(top, bottom):
            start = (row * width + left) * 4
            end = (row * width + right) * 4
            digest.update(rgba[start:end])
        return digest.hexdigest()


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


def build_runtime(settings: Settings, store: SQLiteStore, regions: Iterable[str] = ("resources", "map", "events", "build_menu", "dialog")) -> GovernorRuntime:
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
    latest_ui_elements: dict[str, dict] = {}

    def observe_state() -> dict:
        state = aggregator.aggregate(source.observe()).to_dict()["values"]
        latest_ui_elements.clear()
        elements = state.get("ui_elements")
        if isinstance(elements, list):
            for element in elements:
                if isinstance(element, dict) and isinstance(element.get("id"), str):
                    latest_ui_elements[element["id"]] = element
        return state

    def resolve_ui_element(element_id: str) -> dict | None:
        if element_id not in latest_ui_elements:
            # The first Governor observation may happen before a live action is
            # preflighted. Reuse the local ROI cache and refresh this resolver
            # view without forcing unnecessary Vision calls.
            observe_state()
        return latest_ui_elements.get(element_id)

    if settings.execution_mode == "dry-run":
        executor = DryRunExecutor()
        verifier = None
    else:
        translator = SkillTranslator(ui_element_supplier=resolve_ui_element)
        adapter = WindowsSendInputAdapter(
            window,
            Win32SendInputBackend(),
            enabled=True,
            allow_clicks=True,
            allow_keyboard=True,
        )
        executor = InputActionExecutor(adapter, translator=translator, observe_state=observe_state)
        verifier = SemanticStateVerifier(observe_state)
    watchdog = Watchdog(store)
    actions = ActionEngine(
        settings,
        store,
        executor,
        verifier,
        preflight=translator.validate_live if settings.execution_mode != "dry-run" else None,
    )
    governor = Governor(store, client, actions, watchdog, model=settings.deepseek_reasoning_model, state_aggregator=aggregator)
    loop = GovernorLoop(source, governor, store, watchdog)
    return GovernorRuntime(loop=loop, source=source, governor=governor)
