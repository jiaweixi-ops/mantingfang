from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable, Iterable

from .actions import ActionEngine, DryRunExecutor
from .capture import CapturedFrame, ClientAreaCapture, WindowsGraphicsCaptureBackend
from .config import Settings
from .qwen import QwenClient, QwenConfigurationError
from .events import MajorEventCoordinator, MajorEventDetector
from .feishu import CommandRouter, FeishuGateway
from .feishu_http import FeishuApiClient, FeishuHttpTransport
from .governor import Governor
from .input import Win32SendInputBackend, WindowsSendInputAdapter
from .loop import CompositeObservationSource, GovernorLoop
from .memory import MemoryProfile, MemorySampler, WindowsMemoryBackend, WindowsProcessEnumerator
from .perception import PerceptionEngine, RegionCatalog
from .reporting import ReportService
from .skills import InputActionExecutor, SkillTranslator
from .state import StateAggregator
from .storage import SQLiteStore
from .telemetry import RuntimeTelemetryClient, RuntimeTelemetryObservationSource
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
    change_thresholds: dict[str, float] = field(default_factory=lambda: {
        "resources": 0.005,
        "events": 0.005,
        "dialog": 0.005,
        "build_menu": 0.01,
        "map": 0.03,
    })
    clock: Callable[[], float] = time.monotonic
    _cache: dict[str, tuple[bytes, float, object]] = field(default_factory=dict, init=False, repr=False)
    last_changed_regions: tuple[str, ...] = field(default_factory=tuple, init=False)
    last_change_scores: dict[str, float] = field(default_factory=dict, init=False)
    last_frame: CapturedFrame | None = field(default=None, init=False, repr=False)

    def observe(self):
        frame = self.capture.capture()
        self.last_frame = frame
        now = self.clock()
        observations = []
        changed: list[str] = []
        scores: dict[str, float] = {}
        for region_name in self.regions:
            signature = self._region_signature(frame.rgba, frame.width, frame.height, region_name)
            cached = self._cache.get(region_name)
            if cached is not None:
                cached_signature, analyzed_at, observation = cached
                score = self._change_score(cached_signature, signature)
                scores[region_name] = score
                threshold = self.change_thresholds.get(region_name, 0.01)
                if score <= threshold and now - analyzed_at < self.force_refresh_seconds:
                    observations.append(observation)
                    continue
            observation = self.perception.observe_rgba(
                frame.rgba,
                frame.width,
                frame.height,
                region_name,
                context="Governor 运行时状态采集",
            )
            elements = observation.data.get("ui_elements")
            capture_window = getattr(self.capture, "window", None)
            capture_info = getattr(self.capture, "last_info", None)
            if isinstance(elements, list) and capture_window is not None and capture_info is not None:
                geometry = capture_window.geometry_snapshot(capture_info).to_dict()
                observation.data["ui_elements"] = [
                    {**element, "geometry_snapshot": geometry}
                    for element in elements
                    if isinstance(element, dict)
                ]
            self._cache[region_name] = (signature, now, observation)
            observations.append(observation)
            changed.append(region_name)
        self.last_changed_regions = tuple(changed)
        self.last_change_scores = scores
        return observations

    def _region_signature(self, rgba: bytes, width: int, height: int, region_name: str, size: int = 64) -> bytes:
        left, top, right, bottom = self.perception.regions.get(region_name).crop_box(width, height)
        crop_width, crop_height = right - left, bottom - top
        signature = bytearray()
        for output_y in range(size):
            source_y = min(bottom - 1, top + int((output_y + 0.5) * crop_height / size))
            for output_x in range(size):
                source_x = min(right - 1, left + int((output_x + 0.5) * crop_width / size))
                offset = (source_y * width + source_x) * 4
                red, green, blue = rgba[offset:offset + 3]
                signature.append((299 * red + 587 * green + 114 * blue) // 1000)
        return bytes(signature)

    @staticmethod
    def _change_score(previous: bytes, current: bytes) -> float:
        if len(previous) != len(current) or not current:
            return 1.0
        return sum(abs(left - right) for left, right in zip(previous, current)) / (255 * len(current))


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
    if not settings.qwen_api_key:
        raise QwenConfigurationError("QWEN_API_KEY is not configured; run requires a real Qwen endpoint")
    if not settings.qwen_reasoning_model:
        raise QwenConfigurationError("QWEN_REASONING_MODEL is not configured")
    if not settings.qwen_vision_model:
        raise QwenConfigurationError("QWEN_VISION_MODEL is not configured")
    client = QwenClient(
        settings.qwen_api_base,
        settings.qwen_api_key,
        settings.qwen_reasoning_model,
        usage_callback=store.record_token_usage,
    )
    window = SteamWindowAdapter(settings.game_window_title, Win32WindowBackend())
    # Production perception is window-scoped WGC.  If WGC is unavailable or
    # fails, propagate the error; never silently reintroduce GDI/desktop capture.
    capture = ClientAreaCapture(window, WindowsGraphicsCaptureBackend(), reject_near_black=True)
    perception = PerceptionEngine(client, RegionCatalog(), model=settings.qwen_vision_model)
    vision_source = SteamVisionObservationSource(capture, perception, tuple(regions))
    sources = []
    if settings.runtime_telemetry_enabled:
        game_info = window.locate()
        game_pid = window.backend.window_process_id(game_info.hwnd)
        if game_pid is None:
            raise RuntimeConfigurationError("runtime telemetry requires a readable Song PID")
        sources.append(RuntimeTelemetryObservationSource(RuntimeTelemetryClient(
            settings.runtime_bridge_url,
            expected_pid=game_pid,
            expected_game_version=settings.runtime_game_version,
        )))
    sources.append(vision_source)
    if settings.memory_profile_path is not None:
        profile = MemoryProfile.from_json(settings.memory_profile_path)
        sources.append(MemoryObservationSource(MemorySampler(profile, WindowsProcessEnumerator(), WindowsMemoryBackend())))
    source = CompositeObservationSource(tuple(sources))
    aggregator = StateAggregator()
    watchdog = Watchdog(store)
    latest_ui_elements: dict[tuple[str, str], dict] = {}

    def observe_state() -> dict:
        state = aggregator.aggregate(source.observe()).to_dict()["values"]
        latest_ui_elements.clear()
        elements_by_region = state.get("ui_elements_by_region")
        if isinstance(elements_by_region, dict):
            for region_name, elements in elements_by_region.items():
                if isinstance(region_name, str) and isinstance(elements, list):
                    for element in elements:
                        if isinstance(element, dict) and isinstance(element.get("id"), str):
                            latest_ui_elements[(region_name, element["id"])] = element
        return state

    def resolve_ui_element(region_name: str, element_id: str) -> dict | None:
        if (region_name, element_id) not in latest_ui_elements:
            # The first Governor observation may happen before a live action is
            # preflighted. Reuse the local ROI cache and refresh this resolver
            # view without forcing unnecessary Vision calls.
            observe_state()
        return latest_ui_elements.get((region_name, element_id))

    gateway: FeishuGateway | None = None
    if settings.feishu_app_id and settings.feishu_app_secret and settings.feishu_target_chat_id:
        feishu_client = FeishuApiClient(settings.feishu_app_id, settings.feishu_app_secret, settings.feishu_api_base)
        gateway = FeishuGateway(
            CommandRouter(store, ReportService(store), watchdog),
            FeishuHttpTransport(feishu_client, settings.feishu_target_chat_id),
            record_event=False,
        )

    def enrich_major_event(event):
        screenshot_path: Path | None = None
        if vision_source.last_frame is not None:
            screenshot_path = settings.db_path.parent / "screenshots" / f"major-event-{event.id}.png"
            screenshot_path.parent.mkdir(parents=True, exist_ok=True)
            screenshot_path.write_bytes(vision_source.last_frame.png)
        return replace(event, screenshot_path=str(screenshot_path) if screenshot_path else None)

    event_coordinator = MajorEventCoordinator(
        MajorEventDetector(store),
        store,
        watchdog,
        notify=gateway.notify_major_event if gateway is not None else None,
        enrich=enrich_major_event,
    )

    if settings.execution_mode == "dry-run":
        executor = DryRunExecutor()
        verifier = None
    else:
        translator = SkillTranslator(ui_element_supplier=resolve_ui_element)
        live_info = window.locate(restore_minimized=True)
        live_pid = window.backend.window_process_id(live_info.hwnd)
        if live_pid is None:
            raise RuntimeConfigurationError("live input requires a readable Song PID")
        adapter = WindowsSendInputAdapter(
            window,
            Win32SendInputBackend(),
            enabled=True,
            allow_clicks=True,
            allow_keyboard=True,
            expected_pid=live_pid,
            auto_foreground=settings.auto_foreground,
            restore_previous_foreground=settings.restore_previous_foreground,
            foreground_stable_seconds=settings.foreground_stable_seconds,
            foreground_timeout_seconds=settings.foreground_timeout_seconds,
        )
        executor = InputActionExecutor(adapter, translator=translator, observe_state=observe_state)
        verifier = SemanticStateVerifier(observe_state)
    actions = ActionEngine(
        settings,
        store,
        executor,
        verifier,
        preflight=translator.validate_live if settings.execution_mode != "dry-run" else None,
    )
    governor = Governor(
        store,
        client,
        actions,
        watchdog,
        model=settings.qwen_reasoning_model,
        state_aggregator=aggregator,
        major_event_handler=event_coordinator.handle,
    )
    loop = GovernorLoop(source, governor, store, watchdog)
    return GovernorRuntime(loop=loop, source=source, governor=governor)
