from __future__ import annotations

import json
import base64
import hashlib
import io
import struct
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from ai_governor.actions import ActionEngine, DryRunExecutor
from ai_governor.capture import (
    CaptureBackendUnavailable,
    CaptureBackendFailure,
    CapturedFrame,
    ClientAreaCapture,
    WindowsGraphicsCaptureBackend,
    Win32ClientCaptureBackend,
    crop_rgba_to_client,
    encode_rgba_png,
    is_near_black_frame,
)
from ai_governor.input import DryRunInputAdapter, InputCommand, InputDisabled, WindowsSendInputAdapter
from ai_governor.loop import CompositeObservationSource, GovernorLoop
from ai_governor.config import Settings, load_persisted_settings, save_persisted_settings
from ai_governor.cli import build_parser
from ai_governor.deepseek import DeepSeekClient, DeepSeekRequestError
from ai_governor.e2e import BuildMenuE2EHarness, E2EConfigurationError, finalize_build_menu_calibration, run_read_only_preflight
from ai_governor.events import MajorEventCoordinator, MajorEventDetector
from ai_governor.feishu import CommandRouter, NullFeishuTransport, FeishuGateway
from ai_governor.feishu_http import FeishuApiClient, FeishuEventHandler, FeishuHttpTransport, FeishuPayloadCipher
from ai_governor.governor import Governor
from ai_governor.models import ActionPlan, Goal, MajorEvent, Observation, PlannedAction, RiskLevel
from ai_governor.memory import MemoryAccessError, MemoryProfile, MemorySampler
from ai_governor.perception import PerceptionEngine, RegionCatalog
from ai_governor.reporting import ReportService
from ai_governor.runtime import SteamVisionObservationSource
from ai_governor.storage import SQLiteStore
from ai_governor.state import StateAggregator
from ai_governor.supervisor import GovernorSupervisor
from ai_governor.watchdog import Watchdog
from ai_governor.window import ForegroundTimeout, SteamWindowAdapter, WindowNotFound, WindowNotForeground
from ai_governor.skills import InputActionExecutor, PreActionValidationError, SkillTranslationError, SkillTranslator
from ai_governor.verification import ScreenshotVerifier, SemanticStateVerifier


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


def test_store_records_token_usage(store: SQLiteStore) -> None:
    store.record_token_usage({"kind": "vision", "model": "deepseek-vl", "prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14})
    assert store.token_usage_totals() == {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14}


def test_daily_report_includes_local_summary_and_state_delta(store: SQLiteStore, tmp_path: Path) -> None:
    store.add_observation(Observation({"values": {"population": 10, "money": 80}}, source="readonly-memory"))
    store.add_observation(Observation({"values": {"population": 12, "money": 100}}, source="readonly-memory"))
    settings = Settings(db_path=tmp_path / "report.db")
    ActionEngine(settings, store, DryRunExecutor()).execute_plan(ActionPlan("daily check", [PlannedAction("inspect_region", {"region": "resources"})]))
    store.record_token_usage({"kind": "strategic", "model": "deepseek-reasoner", "prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25})
    report = ReportService(store).daily_report()
    assert "今天完成了什么" in report
    assert "population" in report and "10 → 12" in report
    assert "DeepSeek 用量" in report and "total=25" in report


def test_deepseek_client_records_usage_without_network() -> None:
    callback = []
    client = DeepSeekClient("https://example.invalid", "key", "model", usage_callback=callback.append)
    client._record_usage({"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}, "model", "strategic")
    assert client.last_usage.to_dict() == {"kind": "strategic", "model": "model", "prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}
    assert callback == [client.last_usage.to_dict()]


def test_persisted_deepseek_settings_round_trip_and_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "settings.json"
    save_persisted_settings(
        {
            "deepseek_api_base": "https://example.test/v1",
            "deepseek_api_key": "secret",
            "deepseek_vision_model": "vision-model",
            "deepseek_reasoning_model": "reasoning-model",
            "ignored": "not persisted",
        },
        path,
    )
    assert load_persisted_settings(path) == {
        "deepseek_api_base": "https://example.test/v1",
        "deepseek_api_key": "secret",
        "deepseek_vision_model": "vision-model",
        "deepseek_reasoning_model": "reasoning-model",
    }
    monkeypatch.setenv("GOVERNOR_SETTINGS_PATH", str(path))
    for name in ("DEEPSEEK_API_BASE", "DEEPSEEK_API_KEY", "DEEPSEEK_VISION_MODEL", "DEEPSEEK_REASONING_MODEL"):
        monkeypatch.delenv(name, raising=False)
    settings = Settings.from_env()
    assert settings.deepseek_reasoning_model == "reasoning-model"
    monkeypatch.setenv("DEEPSEEK_REASONING_MODEL", "environment-model")
    assert Settings.from_env().deepseek_reasoning_model == "environment-model"


def test_cli_exposes_overlay_command() -> None:
    args = build_parser().parse_args(["overlay"])
    assert args.command == "overlay"


def test_deepseek_client_rejects_negative_retry_count() -> None:
    with pytest.raises(ValueError, match="max_retries"):
        DeepSeekClient("https://example.invalid", "key", "model", max_retries=-1)


def test_deepseek_client_retries_http_429_and_records_response_usage(monkeypatch) -> None:
    calls = []

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({
                "choices": [{"message": {"content": json.dumps({"ok": True})}}],
                "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
            }).encode()

    def fake_urlopen(request, timeout):
        calls.append((request.full_url, timeout))
        if len(calls) == 1:
            raise urllib.error.HTTPError(request.full_url, 429, "rate limited", {}, io.BytesIO(b"retry"))
        return Response()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    client = DeepSeekClient("https://example.invalid", "key", "model", max_retries=1, backoff_seconds=0, sleep_fn=lambda _: None)
    assert client.complete_json([{"role": "user", "content": "{}"}]) == {"ok": True}
    assert len(calls) == 2
    assert client.usage_totals["total_tokens"] == 6


def test_deepseek_vision_request_contains_image_in_user_message(monkeypatch) -> None:
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({"choices": [{"message": {"content": '{"vision_probe": true}'}}]}).encode()

    def fake_urlopen(request, timeout):
        captured["payload"] = json.loads(request.data.decode())
        return Response()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    DeepSeekClient("https://example.invalid", "secret-key", "vision-model").analyze_image_json(
        b"png-bytes", "return JSON", model="vision-model"
    )
    messages = captured["payload"]["messages"]
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert messages[1]["content"][1]["type"] == "image_url"
    assert messages[1]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_deepseek_http_error_masks_api_key(monkeypatch) -> None:
    secret = "super-secret-api-key"

    def fake_urlopen(request, timeout):
        raise urllib.error.HTTPError(
            request.full_url,
            400,
            "bad request",
            {},
            io.BytesIO(("server echoed " + secret).encode()),
        )

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(DeepSeekRequestError) as raised:
        DeepSeekClient("https://example.invalid", secret, "vision-model", max_retries=0).complete_json(
            [{"role": "user", "content": "{}"}]
        )
    assert raised.value.status_code == 400
    assert secret not in str(raised.value)
    assert "[REDACTED]" in str(raised.value)


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


def test_skill_translator_accepts_explicit_input_commands() -> None:
    action = PlannedAction("click", {"x_ratio": 0.5, "y_ratio": 0.8})
    commands = SkillTranslator().translate(action)
    assert commands == [InputCommand("click", 0.5, 0.8)]


def test_skill_translator_rejects_unknown_game_skill() -> None:
    with pytest.raises(SkillTranslationError, match="unsupported game skill"):
        SkillTranslator().translate(PlannedAction("build_farm", {"x": 1, "y": 2}))


def test_live_skill_preflight_rejects_missing_semantic_predicate_before_translation() -> None:
    with pytest.raises(PreActionValidationError, match="expected_state or changed_fields"):
        SkillTranslator().validate_live(PlannedAction("OPEN_BUILD_MENU", {"commands": [{"kind": "key_down", "key": 27}]}))


def test_live_skill_preflight_translates_before_input() -> None:
    action = PlannedAction(
        "OPEN_BUILD_MENU",
        {
            "target_region": "build_menu",
            "target_element": "build",
            "changed_fields": ["menu"],
        },
    )
    SkillTranslator(ui_element_supplier=lambda region, _: {"global_bbox": [0.1, 0.82, 0.3, 0.86]}).validate_live(action)


def test_skill_translator_resolves_command_from_observed_ui_element() -> None:
    action = PlannedAction(
        "OPEN_BUILD_MENU",
        {"target_region": "build_menu", "target_element": "build", "changed_fields": ["menu"]},
    )
    translator = SkillTranslator(
        ui_element_supplier=lambda region, element_id: {
            "id": element_id,
            "global_bbox": [0.2, 0.82, 0.3, 0.86],
        }
    )
    command = translator.translate(action)[0]
    assert command.kind == "click"
    assert command.x_ratio == pytest.approx(0.25)
    assert command.y_ratio == pytest.approx(0.84)


def test_action_engine_blocks_live_action_before_executor_on_bad_contract(store: SQLiteStore, tmp_path: Path) -> None:
    class SemanticVerifier:
        semantic = True

        def verify(self, action, execution_result):
            raise AssertionError("post-action verification must not run")

    class ExplodingExecutor:
        def execute(self, action):
            raise AssertionError("executor must not receive an invalid live action")

    settings = Settings(db_path=tmp_path / "preflight.db", execution_mode="live", allow_live_input=True)
    store.set_runtime("live_armed", True)
    engine = ActionEngine(settings, store, ExplodingExecutor(), SemanticVerifier(), SkillTranslator().validate_live)
    result = engine.execute_plan(ActionPlan("preflight", [PlannedAction("OPEN_BUILD_MENU", {"commands": []})]))
    assert result[0]["status"] == "blocked"
    assert "pre-action validation failed" in result[0]["reason"]


def test_input_action_executor_captures_before_and_after_state() -> None:
    class Adapter:
        def execute(self, command):
            return {"kind": command.kind, "simulated": True}

    states = iter([{"menu": "closed"}, {"menu": "open"}])
    result = InputActionExecutor(Adapter(), observe_state=lambda: next(states)).execute(
        PlannedAction("click", {"x_ratio": 0.5, "y_ratio": 0.5})
    )
    assert result["simulated"] is True
    assert result["before_state"] == {"menu": "closed"}
    assert result["after_state"] == {"menu": "open"}


def test_semantic_verifier_requires_observable_state_change() -> None:
    verifier = SemanticStateVerifier(lambda: {"menu": "open"}, timeout_seconds=0)
    result = verifier.verify(
        PlannedAction("open_menu", {"changed_fields": ["menu"]}),
        {"before_state": {"menu": "closed"}},
    )
    assert result["verified"] is True


def test_live_action_requires_explicit_policy_and_semantic_verifier(store: SQLiteStore, tmp_path: Path) -> None:
    settings = Settings(db_path=tmp_path / "governor.db", execution_mode="live", allow_live_input=True)
    engine = ActionEngine(settings, store, DryRunExecutor())
    action = PlannedAction("click", {"x_ratio": 0.5, "y_ratio": 0.5})
    result = engine.execute_plan(ActionPlan("live guard", [action]))
    assert result[0]["status"] == "blocked"
    assert "arming" in result[0]["reason"]
    store.set_runtime("live_armed", True)
    second = engine.execute_plan(ActionPlan("live semantic guard", [action]))
    assert second[0]["status"] == "blocked"
    assert "semantic" in second[0]["reason"]


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


def test_governor_loop_passes_multi_source_observations(store: SQLiteStore) -> None:
    class MultiRunner:
        def __init__(self):
            self.observations = []

        def run_observations(self, observations):
            self.observations.append(observations)
            return {"status": "executed"}

    class Source:
        def __init__(self, value):
            self.value = value

        def observe(self):
            return Observation({"value": self.value}, source=str(self.value))

    runner = MultiRunner()
    source = CompositeObservationSource((Source("memory"), Source("vision")))
    cycles = GovernorLoop(source, runner, store, Watchdog(store), interval_seconds=0).run(max_cycles=1)
    assert cycles[0].status == "changed"
    assert [item.source for item in runner.observations[0]] == ["memory", "vision"]


def test_governor_loop_enters_recovery_after_repeated_sensor_errors(store: SQLiteStore) -> None:
    loop = GovernorLoop(SequenceSource(error=RuntimeError("capture unavailable")), RecordingRunner(), store, Watchdog(store), interval_seconds=0, max_observation_errors=2)
    cycles = loop.run(max_cycles=5)
    assert [cycle.status for cycle in cycles] == ["observation_error", "needs_recovery"]
    assert store.get_runtime("recovery_required") is True


def test_supervisor_restarts_unexpected_loop_crash_with_bounded_backoff(store: SQLiteStore) -> None:
    attempts = []
    sleeps = []

    class HealthyLoop:
        def run(self, **kwargs):
            return [type("Cycle", (), {"status": "changed"})()]

    def factory():
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("temporary loop crash")
        return HealthyLoop()

    supervisor = GovernorSupervisor(factory, store, Watchdog(store), max_restarts=2, backoff_seconds=2, sleep_fn=sleeps.append)
    result = supervisor.run(max_cycles=1)
    assert len(result) == 1
    assert attempts == [1, 1]
    assert sleeps == [2]


class FakeFeishuHttp:
    def __init__(self) -> None:
        self.requests = []

    def request(self, method, url, headers, body):
        payload = None if headers.get("Content-Type", "").startswith("multipart/form-data") else json.loads(body.decode("utf-8"))
        self.requests.append((method, url, headers, payload, body))
        if url.endswith("tenant_access_token/internal"):
            return 200, json.dumps({"code": 0, "tenant_access_token": "tenant-token", "expire": 7200}).encode()
        if url.endswith("/open-apis/im/v1/images"):
            return 200, json.dumps({"code": 0, "data": {"image_key": "img_test"}}).encode()
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


def test_feishu_http_transport_uploads_and_sends_image(tmp_path: Path) -> None:
    image = tmp_path / "event.png"
    image.write_bytes(b"png-bytes")
    http = FakeFeishuHttp()
    transport = FeishuHttpTransport(FeishuApiClient("app", "secret", http=http), "oc_test")
    transport.send_image(str(image))
    assert len(http.requests) == 3
    assert http.requests[1][1].endswith("/open-apis/im/v1/images")
    assert b"png-bytes" in http.requests[1][4]
    assert http.requests[2][3]["msg_type"] == "image"


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


def test_feishu_event_handler_decrypts_encrypted_challenge(store: SQLiteStore) -> None:
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    except ImportError:
        pytest.skip("optional cryptography package is unavailable or has a broken native binding")
    key_text = "encrypt-key"
    key = hashlib.sha256(key_text.encode()).digest()
    plain = json.dumps({"type": "url_verification", "token": "verify", "challenge": "encrypted"}).encode()
    padding = 16 - (len(plain) % 16)
    encryptor = Cipher(algorithms.AES(key), modes.CBC(key[:16])).encryptor()
    encoded = base64.b64encode(encryptor.update(plain + bytes([padding]) * padding) + encryptor.finalize()).decode()
    http = FakeFeishuHttp()
    client = FeishuApiClient("app", "secret", http=http)
    router = CommandRouter(store, ReportService(store), Watchdog(store))
    handler = FeishuEventHandler(router, client, verification_token="verify", encrypt_key=key_text)
    assert handler.handle({"encrypt": encoded}) == {"challenge": "encrypted"}
    assert FeishuPayloadCipher.decrypt(encoded, key_text)["challenge"] == "encrypted"


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
    assert store.get_runtime("pending_decision")["status"] == "pending"
    assert "已记录重大事件决策" in router.handle("选择方案 方案一")
    assert store.get_runtime("last_decision")["decision"] == "方案一"
    assert store.get_runtime("paused") is False


def test_decision_resume_command_cannot_bypass_pending_event(store: SQLiteStore) -> None:
    router = CommandRouter(store, ReportService(store), Watchdog(store))
    gateway = FeishuGateway(router, NullFeishuTransport())
    gateway.notify_major_event(MajorEvent("重大剧情", "等待选择", requires_decision=True))
    assert "仍有待决" in router.handle("继续托管")
    assert store.get_runtime("paused") is True


def test_major_event_coordinator_pauses_without_feishu(store: SQLiteStore) -> None:
    watchdog = Watchdog(store)
    coordinator = MajorEventCoordinator(MajorEventDetector(store), store, watchdog)
    event = coordinator.handle([
        Observation(
            {"events": [{"title": "粮食危机", "body": "粮食即将耗尽", "severity": "critical"}]},
            source="deepseek-vision",
            region="events",
        )
    ])[0]
    assert event.requires_decision is True
    assert store.get_runtime("paused") is True
    assert store.get_runtime("pending_decision")["status"] == "pending"
    assert store.recent_events(1)[0]["title"] == "粮食危机"


def test_major_event_screenshot_is_sent_before_text(store: SQLiteStore, tmp_path: Path) -> None:
    screenshot = tmp_path / "event.png"
    screenshot.write_bytes(b"png")
    router = CommandRouter(store, ReportService(store), Watchdog(store))
    transport = NullFeishuTransport()
    gateway = FeishuGateway(router, transport)
    gateway.notify_major_event(MajorEvent("事件", "正文", screenshot_path=str(screenshot)))
    assert transport.sent_images == [str(screenshot)]
    assert transport.sent[-1].startswith("🟡 事件")


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


def test_canonical_state_keeps_ui_elements_separated_by_region() -> None:
    state = StateAggregator().aggregate([
        Observation({"ui_elements": [{"id": "build", "global_bbox": [0.1, 0.8, 0.2, 0.9]}]}, source="deepseek-vision", region="build_menu"),
        Observation({"ui_elements": [{"id": "confirm", "global_bbox": [0.4, 0.4, 0.6, 0.6]}]}, source="deepseek-vision", region="dialog"),
    ])
    assert set(state.values["ui_elements_by_region"]) == {"build_menu", "dialog"}
    assert state.values["ui_elements_by_region"]["dialog"][0]["id"] == "confirm"


def test_major_event_detector_deduplicates_structured_vision_events(store: SQLiteStore) -> None:
    detector = MajorEventDetector(store)
    observation = Observation({
        "events": [{"title": "粮食危机", "body": "粮食即将耗尽", "severity": "critical"}],
    }, source="deepseek-vision", region="events")
    first = detector.detect([observation])
    assert len(first) == 1
    assert first[0].requires_decision is True
    store.add_event(first[0])
    assert detector.detect([observation]) == []


def test_governor_invokes_major_event_handler_before_strategy(store: SQLiteStore, tmp_path: Path) -> None:
    settings = Settings(db_path=tmp_path / "events.db")
    engine = ActionEngine(settings, store, DryRunExecutor())
    seen = []
    governor = Governor(
        store,
        FakeBrain({"reason": "observe", "actions": []}),
        engine,
        Watchdog(store),
        major_event_handler=lambda observations: seen.extend(observations),
    )
    result = governor.run_cycle(Observation({"population": 1}))
    assert result["status"] == "executed"
    assert len(seen) == 1


def test_build_menu_e2e_requires_explicit_confirmation(store: SQLiteStore, tmp_path: Path) -> None:
    settings = Settings(db_path=tmp_path / "e2e.db", execution_mode="live", allow_live_input=True)
    store.set_runtime("live_armed", True)
    fake_actions = type("Actions", (), {"verifier": type("Verifier", (), {"semantic": True})()})()
    harness = BuildMenuE2EHarness(settings, store, fake_actions)
    with pytest.raises(E2EConfigurationError, match="confirm-live-e2e"):
        harness.run(confirm_live=False)


def test_build_menu_e2e_stops_on_first_failed_action(store: SQLiteStore, tmp_path: Path) -> None:
    settings = Settings(db_path=tmp_path / "e2e.db", execution_mode="live", allow_live_input=True)
    store.set_runtime("live_armed", True)

    class FakeActions:
        verifier = type("Verifier", (), {"semantic": True})()

        def __init__(self):
            self.calls = 0
            self.plans = []

        def execute_plan(self, plan):
            self.calls += 1
            self.plans.append(plan)
            return [{"status": "succeeded" if self.calls == 1 else "blocked", "error": "foreground mismatch"}]

    actions = FakeActions()
    result = BuildMenuE2EHarness(
        settings,
        store,
        actions,
        open_region="build_controls",
        open_element="build_menu_toggle",
        close_region="build_controls",
        close_element="build_menu_toggle",
    ).run(attempts=100, confirm_live=True)
    assert result["completed_attempts"] == 0
    assert result["open_succeeded"] == 1
    assert result["blocked"] == 1
    assert result["passed"] is False
    assert actions.plans[0].actions[0].payload["target_region"] == "build_controls"
    assert actions.plans[1].actions[0].payload["target_region"] == "build_controls"


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


def test_perception_normalizes_valid_ui_elements() -> None:
    class Analyzer(FakeAnalyzer):
        def analyze_image_json(self, image, prompt, *, model=None):
            return {
                "build_menu_open": True,
                "current_screen": "build_menu",
                "ui_elements": [{"id": "random-build-id", "role": "BUILD_MENU_TOGGLE", "label": "建造", "confidence": 0.95, "bbox": [0.1, 0.2, 0.3, 0.4]}],
            }

    observation = PerceptionEngine(Analyzer(), RegionCatalog()).observe(b"frame", "build_menu")
    assert observation.data["ui_elements"][0]["id"] == "build_menu_toggle"
    assert observation.data["ui_elements"][0]["raw_id"] == "random-build-id"
    assert observation.data["ui_elements"][0]["bbox"] == [0.1, 0.2, 0.3, 0.4]
    assert observation.data["ui_elements"][0]["global_bbox"] == pytest.approx([0.048, 0.824, 0.144, 0.868])


def test_build_ui_roles_map_to_distinct_canonical_ids() -> None:
    class Analyzer(FakeAnalyzer):
        def analyze_image_json(self, image, prompt, *, model=None):
            return {
                "build_menu_open": True,
                "current_screen": "build_menu",
                "ui_elements": [
                    {"id": "random-open", "role": "BUILD_MENU_OPEN", "label": "打开", "confidence": 0.95, "bbox": [0.1, 0.1, 0.2, 0.2]},
                    {"id": "random-close", "role": "BUILD_MENU_CLOSE", "label": "关闭", "confidence": 0.95, "bbox": [0.3, 0.1, 0.4, 0.2]},
                ],
            }

    elements = PerceptionEngine(Analyzer(), RegionCatalog()).observe(b"frame", "build_controls").data["ui_elements"]
    assert [item["id"] for item in elements] == ["build_menu_open_control", "build_menu_close_control"]
    assert [item["raw_id"] for item in elements] == ["random-open", "random-close"]


def test_build_controls_global_bbox_uses_full_client_coordinates() -> None:
    class Analyzer(FakeAnalyzer):
        def analyze_image_json(self, image, prompt, *, model=None):
            return {
                "build_menu_open": False,
                "current_screen": "city",
                "ui_elements": [{"id": "toggle-any", "role": "BUILD_MENU_TOGGLE", "label": "建筑", "confidence": 0.95, "bbox": [0.1, 0.2, 0.3, 0.4]}],
            }

    element = PerceptionEngine(Analyzer(), RegionCatalog()).observe(b"frame", "build_controls").data["ui_elements"][0]
    assert element["id"] == "build_menu_toggle"
    assert element["global_bbox"] == pytest.approx([0.1, 0.72, 0.3, 0.79])


def test_calibration_finalize_detects_toggle_and_requires_both_states(tmp_path: Path) -> None:
    assert finalize_build_menu_calibration(tmp_path)["live_e2e_ready"] is False
    open_data = {
        "build_menu_open": True,
        "calibration_pass": True,
        "resolution": [1280, 960],
        "selected_target": {
            "role": "BUILD_MENU_TOGGLE",
            "canonical_id": "build_menu_toggle",
            "region": "build_controls",
            "global_bbox": [0.1, 0.8, 0.2, 0.9],
        },
    }
    closed_data = {
        "build_menu_open": False,
        "calibration_pass": True,
        "selected_target": {
            "role": "BUILD_MENU_TOGGLE",
            "canonical_id": "build_menu_toggle",
            "region": "build_controls",
            "global_bbox": [0.1, 0.8, 0.2, 0.9],
        },
    }
    (tmp_path / "build_menu_open_calibration.json").write_text(json.dumps(open_data), encoding="utf-8")
    (tmp_path / "build_menu_closed_calibration.json").write_text(json.dumps(closed_data), encoding="utf-8")
    result = finalize_build_menu_calibration(tmp_path)
    assert result["control_mode"] == "TOGGLE"
    assert result["live_e2e_ready"] is True


def test_calibration_finalize_detects_separate_open_close_controls(tmp_path: Path) -> None:
    common = {"calibration_pass": True, "resolution": [1280, 960]}
    (tmp_path / "build_menu_open_calibration.json").write_text(json.dumps({
        **common,
        "build_menu_open": True,
        "selected_target": {"role": "BUILD_MENU_CLOSE", "canonical_id": "build_menu_close_control", "region": "build_controls", "global_bbox": [0.1, 0.8, 0.2, 0.9]},
    }), encoding="utf-8")
    (tmp_path / "build_menu_closed_calibration.json").write_text(json.dumps({
        **common,
        "build_menu_open": False,
        "selected_target": {"role": "BUILD_MENU_OPEN", "canonical_id": "build_menu_open_control", "region": "build_controls", "global_bbox": [0.7, 0.8, 0.8, 0.9]},
    }), encoding="utf-8")
    result = finalize_build_menu_calibration(tmp_path)
    assert result["control_mode"] == "SEPARATE"
    assert result["open"]["canonical_id"] == "build_menu_open_control"
    assert result["close"]["canonical_id"] == "build_menu_close_control"


def test_perception_rejects_invalid_ui_element_bbox() -> None:
    class Analyzer(FakeAnalyzer):
        def analyze_image_json(self, image, prompt, *, model=None):
            return {
                "build_menu_open": True,
                "current_screen": "build_menu",
                "ui_elements": [{"id": "build", "bbox": [0.8, 0.2, 0.3, 0.4]}],
            }

    with pytest.raises(ValueError, match="normalized coordinates"):
        PerceptionEngine(Analyzer(), RegionCatalog()).observe(b"frame", "build_menu")


def test_perception_rejects_missing_build_menu_semantic_schema() -> None:
    class Analyzer(FakeAnalyzer):
        def analyze_image_json(self, image, prompt, *, model=None):
            return {"ui_elements": []}

    with pytest.raises(ValueError, match="build_menu_open"):
        PerceptionEngine(Analyzer(), RegionCatalog()).observe(b"frame", "build_menu")


def test_perception_requires_dialog_semantic_schema() -> None:
    class Analyzer(FakeAnalyzer):
        def analyze_image_json(self, image, prompt, *, model=None):
            return {"dialog_open": True, "current_screen": "dialog", "options": [], "ui_elements": []}

    observation = PerceptionEngine(Analyzer(), RegionCatalog()).observe(b"frame", "dialog")
    assert observation.data["dialog_open"] is True
    assert observation.data["options"] == []


def test_perception_crops_rgba_before_analysis() -> None:
    analyzer = FakeAnalyzer()
    engine = PerceptionEngine(analyzer, RegionCatalog())
    observation = engine.observe_rgba(bytes((1, 2, 3, 255)) * (100 * 100), 100, 100, "resources")
    assert observation.data["crop_box"] == (0, 0, 30, 16)
    assert analyzer.last_image.startswith(b"\x89PNG\r\n\x1a\n")
    assert struct.unpack(">II", analyzer.last_image[16:24]) == (30, 16)


def test_steam_vision_source_reuses_unchanged_roi_analysis() -> None:
    class Capture:
        def __init__(self) -> None:
            self.rgba = bytes((1, 2, 3, 255)) * (100 * 100)

        def capture(self):
            return CapturedFrame(100, 100, b"frame", self.rgba)

    class Perception:
        regions = RegionCatalog()

        def __init__(self):
            self.calls = []

        def observe_rgba(self, rgba, width, height, region_name, *, context=""):
            self.calls.append(region_name)
            return Observation({"region_value": region_name}, source="deepseek-vision", region=region_name)

    clock_value = [0.0]
    perception = Perception()
    source = SteamVisionObservationSource(
        Capture(),
        perception,
        ("resources", "map"),
        force_refresh_seconds=60.0,
        clock=lambda: clock_value[0],
    )
    first = source.observe()
    second = source.observe()
    assert perception.calls == ["resources", "map"]
    assert second == first
    assert source.last_changed_regions == ()

    changed = bytearray(source.capture.rgba)
    for row in range(0, 16):
        for column in range(0, 30):
            offset = (row * 100 + column) * 4
            changed[offset:offset + 4] = bytes((255, 255, 255, 255))
    source.capture.rgba = bytes(changed)
    third = source.observe()
    assert perception.calls == ["resources", "map", "resources"]
    assert source.last_changed_regions == ("resources",)
    assert third[1] is first[1]


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
        self.foreground = 99

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

    def foreground_window(self):
        return self.foreground

    def window_process_id(self, hwnd: int):
        return 39408 if hwnd == 99 else 12116

    def window_title(self, hwnd: int):
        return "Song" if hwnd == 99 else "ChatGPT"

    def process_name(self, pid: int | None):
        return {39408: "Song.exe", 12116: "ChatGPT.exe"}.get(pid)


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


def test_window_adapter_waits_for_stable_foreground_without_focusing() -> None:
    backend = FakeWindowBackend()
    backend.foreground = 1
    now = 0.0

    def clock() -> float:
        return now

    # The fake sleep keeps the game foreground after the first poll to model a
    # user selecting Song; the adapter must never call a focus API.
    calls = 0

    def controlled_sleep(seconds: float) -> None:
        nonlocal now, calls
        now += seconds
        calls += 1
        if calls >= 1:
            backend.foreground = 99

    backend.foreground = 1
    result = SteamWindowAdapter("满庭芳：宋上繁华", backend).wait_for_foreground(
        timeout_seconds=5,
        stable_seconds=1.5,
        poll_seconds=0.5,
        clock=clock,
        sleep=controlled_sleep,
    )
    assert result.hwnd == 99
    assert calls >= 3


def test_window_adapter_foreground_wait_times_out_without_focusing() -> None:
    backend = FakeWindowBackend()
    now = 0.0

    def clock() -> float:
        return now

    def sleep(seconds: float) -> None:
        nonlocal now
        now += seconds

    with pytest.raises(ForegroundTimeout, match="FOREGROUND_TIMEOUT"):
        SteamWindowAdapter("满庭芳：宋上繁华", backend).wait_for_foreground(
            timeout_seconds=1,
            stable_seconds=1,
            poll_seconds=0.5,
            clock=clock,
            sleep=sleep,
        )


def test_window_diagnostic_marks_different_hwnd_same_game_process() -> None:
    backend = FakeWindowBackend()
    backend.foreground = 100
    backend.window_process_id = lambda hwnd: 39408
    backend.window_title = lambda hwnd: "Song child"
    diagnostic = SteamWindowAdapter("满庭芳：宋上繁华", backend).foreground_diagnostic()
    assert diagnostic.foreground_matches_game_hwnd is False
    assert diagnostic.same_process is True
    assert diagnostic.flags == ("FOREGROUND_SAME_GAME_PROCESS_DIFFERENT_HWND",)


def test_read_only_preflight_does_not_require_foreground(monkeypatch, tmp_path: Path, store: SQLiteStore) -> None:
    class VisibleCaptureBackend:
        backend_name = "WindowsGraphicsCaptureBackend"
        raster_mode = "WGC"
        is_occlusion_independent = True
        supports_directx_window_capture = True

        def capture_rgba(self, hwnd: int, width: int, height: int) -> bytes:
            return bytes((80, 90, 100, 255)) * (width * height)

    class VisionClient:
        def __init__(self, *args, **kwargs):
            pass

        def analyze_image_json(self, image, prompt, *, model=None):
            if "关注区域：build_menu" in prompt:
                return {
                    "build_menu_open": False,
                    "current_screen": "city",
                    "confidence": 0.91,
                        "ui_elements": [{"id": "random-open", "role": "BUILD_MENU_TOGGLE", "label": "建筑", "confidence": 0.95, "bbox": [0.1, 0.1, 0.2, 0.2]}],
                }
            return {
                "dialog_open": False,
                "current_screen": "city",
                "options": [],
                "confidence": 0.88,
                "ui_elements": [{"id": "random-close", "role": "BUILD_MENU_CLOSE", "label": "关闭", "confidence": 0.95, "bbox": [0.7, 0.7, 0.8, 0.8]}],
            }

    backend = FakeWindowBackend()
    backend.foreground = 100
    monkeypatch.setattr("ai_governor.e2e.Win32WindowBackend", lambda: backend)
    monkeypatch.setattr("ai_governor.e2e.WindowsGraphicsCaptureBackend", VisibleCaptureBackend)
    monkeypatch.setattr("ai_governor.e2e.DeepSeekClient", VisionClient)
    settings = Settings(
        db_path=tmp_path / "preflight.db",
        deepseek_api_key="test-key",
        deepseek_vision_model="test-vision",
    )
    report = run_read_only_preflight(settings, store, output_dir=tmp_path / "e2e")
    assert report["foreground"]["foreground_matches_game_hwnd"] is False
    assert report["capture"]["raster_mode"] == "WGC"
    assert report["vision"]["build_menu"]["ui_elements"]
    assert report["vision"]["dialog"]["ui_elements"]
    assert report["elements"]["open"]["found"] is True
    assert report["elements"]["close"]["found"] is True
    assert report["capture_pass"] is True
    assert report["vision_pass"] is True
    assert report["action_target_calibrated"] is False
    assert report["live_e2e_ready"] is False
    assert report["status"] == "ACTION_TARGET_CALIBRATION_PENDING"


def test_read_only_preflight_does_not_fallback_when_wgc_is_unavailable(monkeypatch, tmp_path: Path, store: SQLiteStore) -> None:
    backend = FakeWindowBackend()
    monkeypatch.setattr("ai_governor.e2e.Win32WindowBackend", lambda: backend)

    def unavailable():
        raise CaptureBackendUnavailable("WGC_UNAVAILABLE: test")

    monkeypatch.setattr("ai_governor.e2e.WindowsGraphicsCaptureBackend", unavailable)
    settings = Settings(
        db_path=tmp_path / "preflight-wgc.db",
        deepseek_api_key="test-key",
        deepseek_vision_model="test-vision",
    )
    with pytest.raises(CaptureBackendUnavailable, match="WGC_UNAVAILABLE"):
        run_read_only_preflight(settings, store, output_dir=tmp_path / "e2e")


def test_win32_capture_defaults_to_srccopy_without_captureblt() -> None:
    assert Win32ClientCaptureBackend.DEFAULT_RASTER_OP == Win32ClientCaptureBackend.SRCCOPY
    assert not (Win32ClientCaptureBackend.DEFAULT_RASTER_OP & Win32ClientCaptureBackend.CAPTUREBLT)
    assert Win32ClientCaptureBackend.DEFAULT_RASTER_MODE == "SRCCOPY"


def test_capture_backend_capabilities_distinguish_gdi_and_wgc() -> None:
    assert Win32ClientCaptureBackend.is_occlusion_independent is False
    assert Win32ClientCaptureBackend.supports_directx_window_capture is False
    assert WindowsGraphicsCaptureBackend.is_occlusion_independent is True
    assert WindowsGraphicsCaptureBackend.supports_directx_window_capture is True


def test_wgc_client_crop_removes_window_chrome_without_desktop_coordinates() -> None:
    width, height = 1282, 992
    source = bytearray(width * height * 4)
    for y in range(height):
        for x in range(width):
            offset = (y * width + x) * 4
            source[offset:offset + 4] = bytes((x % 256, y % 256, 7, 255))
    cropped = crop_rgba_to_client(bytes(source), width, height, 1280, 960, 1, 31, 1282, 992)
    assert len(cropped) == 1280 * 960 * 4
    assert cropped[:4] == bytes((1, 31, 7, 255))


def test_wgc_unavailable_is_explicit_and_does_not_downgrade(monkeypatch) -> None:
    monkeypatch.setattr("ai_governor.capture.os.name", "posix")
    with pytest.raises(CaptureBackendUnavailable, match="WGC_UNAVAILABLE"):
        WindowsGraphicsCaptureBackend()


def test_wgc_backend_failure_is_explicit() -> None:
    with pytest.raises(CaptureBackendFailure, match="CAPTURE_BACKEND_FAILURE"):
        crop_rgba_to_client(bytes(4), 1, 1, 2, 2, 0, 0, 1, 1)


def test_capture_diagnostic_marks_near_black_frame_without_fallback() -> None:
    assert is_near_black_frame(bytes((0, 0, 0, 255)) * 100)
    rgba = bytes((0, 0, 0, 255)) * 97 + bytes((255, 255, 255, 255)) * 3
    assert not is_near_black_frame(rgba, min_black_ratio=0.98)


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


def test_live_input_refuses_non_foreground_window() -> None:
    class Backend:
        def move_absolute(self, x, y):
            raise AssertionError("input must not be emitted")

        def mouse_click(self):
            raise AssertionError("input must not be emitted")

        def key(self, virtual_key, down):
            raise AssertionError("input must not be emitted")

    window_backend = FakeWindowBackend()
    window_backend.foreground = 101
    adapter = WindowsSendInputAdapter(
        SteamWindowAdapter("满庭芳：宋上繁华", window_backend),
        Backend(),
        enabled=True,
        allow_clicks=True,
        allow_keyboard=True,
    )
    with pytest.raises(WindowNotForeground, match="not foreground"):
        adapter.execute(InputCommand("click", 0.5, 0.5))


def test_live_input_accepts_exact_game_foreground_with_fake_backend() -> None:
    calls = []

    class Backend:
        def move_absolute(self, x, y):
            calls.append(("move", x, y))

        def mouse_click(self):
            calls.append(("click",))

        def key(self, virtual_key, down):
            calls.append(("key", virtual_key, down))

    adapter = WindowsSendInputAdapter(
        SteamWindowAdapter("满庭芳：宋上繁华", FakeWindowBackend()),
        Backend(),
        enabled=True,
        allow_clicks=True,
        allow_keyboard=True,
    )
    result = adapter.execute(InputCommand("click", 0.5, 0.5))
    assert result["simulated"] is False
    assert calls[-1] == ("click",)


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
