from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest

from ai_governor.actions import ActionEngine, DryRunExecutor
from ai_governor.capture import ClientAreaCapture, encode_rgba_png
from ai_governor.input import DryRunInputAdapter, InputCommand, InputDisabled, WindowsSendInputAdapter
from ai_governor.loop import GovernorLoop
from ai_governor.config import Settings
from ai_governor.feishu import CommandRouter, NullFeishuTransport, FeishuGateway
from ai_governor.feishu_http import FeishuApiClient, FeishuEventHandler, FeishuHttpTransport
from ai_governor.governor import Governor
from ai_governor.models import ActionPlan, Goal, MajorEvent, Observation, PlannedAction, RiskLevel
from ai_governor.memory import MemoryAccessError, MemoryProfile, MemorySampler
from ai_governor.perception import PerceptionEngine, RegionCatalog
from ai_governor.reporting import ReportService
from ai_governor.storage import SQLiteStore
from ai_governor.state import StateAggregator
from ai_governor.watchdog import Watchdog
from ai_governor.window import SteamWindowAdapter, WindowNotFound
from ai_governor.verification import ScreenshotVerifier


@pytest.fixture
def store(tmp_path: Path) -> SQLiteStore:
    value = SQLiteStore(tmp_path / "governor.db")
    yield value
    value.close()


def test_store_round_trip_and_report(store: SQLiteStore) -> None:
    store.add_observation(Observation({"population": 826, "grain": 4200}, source="test", region="resources", confidence=0.95))
    store.add_goal(Goal("人口达到 1000", target={"population": 1000}))
    report = ReportService(store).daily_report()
    assert "826" in report
    assert "人口达到 1000" in report


def test_action_engine_is_dry_run_and_idempotent(store: SQLiteStore, tmp_path: Path) -> None:
    settings = Settings(db_path=tmp_path / "governor.db")
    engine = ActionEngine(settings, store, DryRunExecutor())
    action = PlannedAction("inspect_region", {"region": "resources"}, RiskLevel.SAFE, idempotency_key="once")
    plan = ActionPlan("read resources", [action])
    first = engine.execute_plan(plan)
    second = engine.execute_plan(plan)
    assert first[0]["status"] == "simulated"
    assert second[0]["status"] == "skipped_duplicate"
    assert store.action_by_key("once")["status"] == "simulated"


def test_default_action_idempotency_is_scoped_to_plan(store: SQLiteStore, tmp_path: Path) -> None:
    settings = Settings(db_path=tmp_path / "governor.db")
    engine = ActionEngine(settings, store, DryRunExecutor())
    action = PlannedAction("inspect_region", {"region": "resources"})
    first_plan = ActionPlan("cycle one", [action])
    second_plan = ActionPlan("cycle two", [action])
    assert engine.execute_plan(first_plan)[0]["status"] == "simulated"
    assert engine.execute_plan(first_plan)[0]["status"] == "skipped_duplicate"
    assert engine.execute_plan(second_plan)[0]["status"] == "simulated"


class SequenceSource:
    def __init__(self, observations=None, error: Exception | None = None) -> None:
        self.observations = list(observations or [])
        self.error = error

    def observe(self):
        if self.error is not None:
            raise self.error
        return self.observations.pop(0) if self.observations else Observation({"population": 1})


class RecordingRunner:
    def __init__(self) -> None:
        self.observations = []

    def run_cycle(self, observation):
        self.observations.append(observation)
        return {"status": "executed"}


def test_governor_loop_skips_unchanged_observations(store: SQLiteStore) -> None:
    runner = RecordingRunner()
    source = SequenceSource([Observation({"population": 1}), Observation({"population": 1}), Observation({"population": 2})])
    cycles = GovernorLoop(source, runner, store, Watchdog(store), interval_seconds=0).run(max_cycles=3)
    assert [cycle.status for cycle in cycles] == ["changed", "unchanged", "changed"]
    assert [item.data["population"] for item in runner.observations] == [1, 2]


def test_governor_loop_enters_recovery_after_repeated_sensor_errors(store: SQLiteStore) -> None:
    loop = GovernorLoop(SequenceSource(error=RuntimeError("capture unavailable")), RecordingRunner(), store, Watchdog(store), interval_seconds=0, max_observation_errors=2)
    cycles = loop.run(max_cycles=5)
    assert [cycle.status for cycle in cycles] == ["observation_error", "needs_recovery"]
    assert store.get_runtime("recovery_required") is True


class FakeFeishuHttp:
    def __init__(self) -> None:
        self.requests = []

    def request(self, method, url, headers, body):
        self.requests.append((method, url, headers, json.loads(body.decode("utf-8"))))
        if url.endswith("tenant_access_token/internal"):
            return 200, json.dumps({"code": 0, "tenant_access_token": "tenant-token", "expire": 7200}).encode()
        return 200, json.dumps({"code": 0, "data": {"message_id": "om_test"}}).encode()


def test_feishu_http_transport_caches_token_and_sends_text() -> None:
    http = FakeFeishuHttp()
    client = FeishuApiClient("app", "secret", http=http)
    transport = FeishuHttpTransport(client, "oc_test")
    transport.send_text("hello")
    transport.send_text("again")
    assert len(http.requests) == 3
    assert http.requests[1][1].endswith("im/v1/messages?receive_id_type=chat_id")
    assert http.requests[1][2]["Authorization"] == "Bearer tenant-token"


def test_feishu_event_handler_handles_url_challenge_and_text(store: SQLiteStore) -> None:
    http = FakeFeishuHttp()
    client = FeishuApiClient("app", "secret", http=http)
    router = CommandRouter(store, ReportService(store), Watchdog(store))
    handler = FeishuEventHandler(router, client, verification_token="verify")
    assert handler.handle({"type": "url_verification", "token": "verify", "challenge": "abc"}) == {"challenge": "abc"}
    result = handler.handle({
        "header": {"event_type": "im.message.receive_v1"},
        "event": {"message": {"message_type": "text", "content": json.dumps({"text": "当前状态"}), "chat_id": "oc_test"}},
    })
    assert result["ok"] is True
    assert len(http.requests) == 2


def test_safety_gate_blocks_critical_and_pause(store: SQLiteStore, tmp_path: Path) -> None:
    settings = Settings(db_path=tmp_path / "governor.db")
    engine = ActionEngine(settings, store, DryRunExecutor())
    critical = PlannedAction("choose_story_option", {"option": 2}, RiskLevel.CRITICAL, idempotency_key="story-2")
    result = engine.execute_plan(ActionPlan("event", [critical]))
    assert result[0]["status"] == "blocked"
    Watchdog(store).pause()
    safe = PlannedAction("inspect_region", {}, RiskLevel.SAFE, idempotency_key="paused")
    assert engine.execute_plan(ActionPlan("paused", [safe]))[0]["status"] == "blocked"


def test_feishu_commands_are_on_demand_and_major_events_push(store: SQLiteStore) -> None:
    reports = ReportService(store)
    watchdog = Watchdog(store)
    router = CommandRouter(store, reports, watchdog)
    transport = NullFeishuTransport()
    gateway = FeishuGateway(router, transport)
    assert "日报" in gateway.on_text_message("获取日报")
    assert "已暂停" in gateway.on_text_message("暂停托管")
    assert store.get_runtime("paused") is True
    event = MajorEvent("阶段目标完成", "人口达到 1000", requires_decision=False)
    assert "阶段目标完成" in gateway.notify_major_event(event)
    assert len(transport.sent) == 3


def test_decision_event_pauses_before_notification(store: SQLiteStore) -> None:
    router = CommandRouter(store, ReportService(store), Watchdog(store))
    transport = NullFeishuTransport()
    gateway = FeishuGateway(router, transport)
    event = MajorEvent("重大剧情", "请选择方案", requires_decision=True)
    message = gateway.notify_major_event(event)
    assert store.get_runtime("paused") is True
    assert store.recent_events(1)[0]["title"] == "重大剧情"
    assert "系统已暂停" in message


def test_goal_change_replaces_previous_long_term_goal(store: SQLiteStore) -> None:
    router = CommandRouter(store, ReportService(store), Watchdog(store))
    router.handle("修改目标 人口达到1000")
    router.handle("修改目标 财政保持正增长")
    assert [goal["title"] for goal in store.active_goals()] == ["财政保持正增长"]


class FakeBrain:
    def __init__(self, response: dict) -> None:
        self.response = response

    def complete_json(self, messages, *, model=None, temperature=0):
        assert messages[0]["role"] == "system"
        return self.response


def test_governor_sends_canonical_state_to_brain(store: SQLiteStore, tmp_path: Path) -> None:
    class CapturingBrain(FakeBrain):
        def complete_json(self, messages, *, model=None, temperature=0):
            self.messages = messages
            return super().complete_json(messages, model=model, temperature=temperature)

    settings = Settings(db_path=tmp_path / "governor.db")
    brain = CapturingBrain({"reason": "inspect", "actions": []})
    engine = ActionEngine(settings, store, DryRunExecutor())
    result = Governor(store, brain, engine, Watchdog(store)).run_observations([
        Observation({"population": 8}, source="deepseek-vision", region="resources"),
        Observation({"values": {"population": 9, "food": 100}}, source="readonly-memory", region="memory"),
    ])
    assert result["status"] == "executed"
    assert isinstance(brain.messages[1]["content"], str)
    state = json.loads(brain.messages[1]["content"])["canonical_game_state"]
    assert state["values"] == {"population": 9, "food": 100}
    assert state["provenance"]["population"]["source"] == "readonly-memory"


def test_governor_runs_persisted_safe_cycle(store: SQLiteStore, tmp_path: Path) -> None:
    settings = Settings(db_path=tmp_path / "governor.db")
    response = {"reason": "inspect", "actions": [{"action_type": "inspect_region", "payload": {"region": "resources"}}]}
    engine = ActionEngine(settings, store, DryRunExecutor())
    result = Governor(store, FakeBrain(response), engine, Watchdog(store)).run_cycle(Observation({"population": 8}))
    assert result["status"] == "executed"
    assert result["results"][0]["status"] == "simulated"


def test_canonical_state_prefers_memory_and_records_conflict() -> None:
    state = StateAggregator().aggregate([
        Observation({"population": 100, "money": 50}, source="deepseek-vision", region="resources", observed_at="2026-09-05T10:00:00+00:00"),
        Observation({"values": {"population": 120, "food": 300}}, source="readonly-memory", region="memory", observed_at="2026-09-05T10:00:01+00:00"),
    ])
    assert state.values == {"population": 120, "money": 50, "food": 300}
    assert state.provenance["population"].source == "readonly-memory"
    assert state.conflicts[0]["field"] == "population"


def test_canonical_state_normalizes_chinese_fields_and_keeps_map_data() -> None:
    state = StateAggregator().aggregate([
        Observation({"人口": 8, "粮食": 40}, source="deepseek-vision", region="resources"),
        Observation({"buildings": [{"type": "farm", "x": 3, "y": 4}]}, source="deepseek-vision", region="map"),
    ])
    assert state.values["population"] == 8
    assert state.values["food"] == 40
    assert state.values["buildings"][0]["type"] == "farm"


def test_governor_halts_on_invalid_brain_response(store: SQLiteStore, tmp_path: Path) -> None:
    settings = Settings(db_path=tmp_path / "governor.db")
    engine = ActionEngine(settings, store, DryRunExecutor())
    result = Governor(store, FakeBrain({"actions": "not-a-list"}), engine, Watchdog(store)).run_cycle(Observation({}))
    assert result["status"] == "needs_recovery"
    assert store.get_runtime("paused") is True


class FakeAnalyzer:
    def __init__(self) -> None:
        self.last_image = b""

    def analyze_image_json(self, image: bytes, prompt: str, *, model: str | None = None) -> dict:
        self.last_image = image
        assert "只读取人口" in prompt
        return {"population": 10, "confidence": 0.9}


def test_perception_uses_task_region() -> None:
    analyzer = FakeAnalyzer()
    engine = PerceptionEngine(analyzer, RegionCatalog())
    observation = engine.observe(b"frame", "resources", context="检查资源")
    assert observation.region == "resources"
    assert observation.data["population"] == 10


def test_perception_crops_rgba_before_analysis() -> None:
    analyzer = FakeAnalyzer()
    engine = PerceptionEngine(analyzer, RegionCatalog())
    observation = engine.observe_rgba(bytes((1, 2, 3, 255)) * (100 * 100), 100, 100, "resources")
    assert observation.data["crop_box"] == (0, 0, 30, 16)
    assert analyzer.last_image.startswith(b"\x89PNG\r\n\x1a\n")
    assert struct.unpack(">II", analyzer.last_image[16:24]) == (30, 16)


def test_region_boxes_are_resolution_independent() -> None:
    region = RegionCatalog().get("resources")
    assert region.crop_box(1920, 1080) == (0, 0, 576, 173)


class FakeMemoryBackend:
    def open_process(self, pid: int):
        return "handle"

    def close_process(self, handle) -> None:
        pass

    def module_base(self, pid: int, module_name: str) -> int:
        return 0x1000

    def read(self, handle, address: int, size: int) -> bytes:
        values = {
            0x1020: struct.pack("<Q", 0x2000),
            0x2010: struct.pack("<i", 1234),
        }
        return values[address][:size]


class FakeProcesses:
    def find(self, process_name: str):
        from ai_governor.memory import ProcessInfo
        return ProcessInfo(42, process_name)


def test_read_only_memory_profile_resolves_typed_pointer_path() -> None:
    profile = MemoryProfile.from_dict({
        "process_name": "game.exe",
        "fields": {"population": {"type": "int32", "base_offset": "0x20", "offsets": ["0x0", "0x10"]}},
    })
    result = MemorySampler(profile, FakeProcesses(), FakeMemoryBackend()).sample()
    assert result["values"] == {"population": 1234}
    assert result["errors"] == {}


def test_memory_profile_rejects_unknown_type() -> None:
    with pytest.raises(ValueError, match="unsupported type"):
        MemoryProfile.from_dict({"process_name": "game.exe", "fields": {"money": {"type": "string"}}})


def test_memory_profile_rejects_invalid_pointer_size() -> None:
    with pytest.raises(ValueError, match="pointer_size"):
        MemoryProfile.from_dict({"process_name": "game.exe", "pointer_size": 16, "fields": {"x": {"type": "int32"}}})


def test_memory_sampler_fails_when_process_is_missing() -> None:
    class Missing:
        def find(self, process_name: str):
            return None
    profile = MemoryProfile.from_dict({"process_name": "missing.exe", "fields": {"x": {"type": "int32"}}})
    with pytest.raises(MemoryAccessError, match="process not found"):
        MemorySampler(profile, Missing(), FakeMemoryBackend()).sample()


class FakeWindowBackend:
    def __init__(self, minimized: bool = False) -> None:
        self.minimized = minimized
        self.restored = False

    def find_window(self, title: str):
        return 99

    def is_window(self, hwnd: int) -> bool:
        return hwnd == 99

    def is_minimized(self, hwnd: int) -> bool:
        return self.minimized and not self.restored

    def restore(self, hwnd: int) -> None:
        self.restored = True

    def client_rect(self, hwnd: int):
        return (0, 0, 1920, 1080)

    def client_to_screen(self, hwnd: int, x: int, y: int):
        return (100 + x, 50 + y)


def test_window_adapter_returns_client_geometry_and_normalized_point() -> None:
    info = SteamWindowAdapter("满庭芳：宋上繁华", FakeWindowBackend()).locate()
    assert info.client_width == 1920
    assert info.client_height == 1080
    assert info.screen_point(0.5, 0.5) == (1060, 590)


def test_window_adapter_can_restore_minimized_window() -> None:
    backend = FakeWindowBackend(minimized=True)
    info = SteamWindowAdapter("满庭芳：宋上繁华", backend).locate(restore_minimized=True)
    assert backend.restored is True
    assert info.minimized is False


def test_window_adapter_fails_closed_when_window_is_missing() -> None:
    class MissingWindow(FakeWindowBackend):
        def find_window(self, title: str):
            return None
    with pytest.raises(WindowNotFound, match="window not found"):
        SteamWindowAdapter("missing", MissingWindow()).locate()


def test_rgba_png_encoder_returns_valid_png_signature() -> None:
    png = encode_rgba_png(1, 1, bytes((255, 0, 0, 255)))
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    assert b"IHDR" in png and b"IEND" in png


class FakeCaptureBackend:
    def capture_rgba(self, hwnd: int, width: int, height: int) -> bytes:
        assert (hwnd, width, height) == (99, 1920, 1080)
        return bytes((0, 0, 0, 255)) * (width * height)


def test_client_capture_uses_window_client_dimensions() -> None:
    frame = ClientAreaCapture(
        SteamWindowAdapter("满庭芳：宋上繁华", FakeWindowBackend()),
        FakeCaptureBackend(),
    ).capture()
    assert (frame.width, frame.height) == (1920, 1080)
    assert frame.png.startswith(b"\x89PNG\r\n\x1a\n")


def test_dry_run_input_uses_window_relative_coordinates() -> None:
    adapter = DryRunInputAdapter(SteamWindowAdapter("满庭芳：宋上繁华", FakeWindowBackend()), [])
    result = adapter.execute(InputCommand("move", 0.5, 0.5))
    assert result["screen_point"] == (1060, 590)
    assert result["simulated"] is True


def test_live_input_is_disabled_by_default() -> None:
    adapter = WindowsSendInputAdapter(SteamWindowAdapter("满庭芳：宋上繁华", FakeWindowBackend()), object())
    with pytest.raises(InputDisabled, match="disabled"):
        adapter.execute(InputCommand("click", 0.5, 0.5))


def test_screenshot_verifier_confirms_window_and_capture() -> None:
    window = SteamWindowAdapter("满庭芳：宋上繁华", FakeWindowBackend())
    capture = ClientAreaCapture(window, FakeCaptureBackend())
    action = PlannedAction("inspect_region", {"region": "resources"})
    result = ScreenshotVerifier(window, capture).verify(action, {"simulated": True})
    assert result["verified"] is True
    assert len(result["png_sha256"]) == 64


def test_action_engine_enters_recovery_when_verification_fails(store: SQLiteStore, tmp_path: Path) -> None:
    class FailingVerifier:
        def verify(self, action, execution_result):
            raise RuntimeError("post-action capture failed")
    settings = Settings(db_path=tmp_path / "governor.db")
    engine = ActionEngine(settings, store, DryRunExecutor(), FailingVerifier())
    action = PlannedAction("inspect_region", {"region": "resources"}, idempotency_key="verify-fail")
    result = engine.execute_plan(ActionPlan("verify", [action]))
    assert result[0]["status"] == "uncertain"
    assert store.get_runtime("recovery_required") is True
