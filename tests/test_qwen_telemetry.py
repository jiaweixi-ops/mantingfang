from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from ai_governor.qwen import QwenClient, QwenConfigurationError
from ai_governor.telemetry import RuntimeTelemetryClient, RuntimeTelemetrySchemaError


class _Response:
    def __init__(self, payload: dict):
        self.payload = payload

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_qwen_requires_key_without_network() -> None:
    with pytest.raises(QwenConfigurationError, match="QWEN_API_KEY"):
        QwenClient("https://example.invalid", None, "qwen-model").complete_json([])


def test_qwen_records_usage_and_uses_compatible_chat_endpoint(monkeypatch) -> None:
    calls = []

    def fake_urlopen(request, timeout):
        calls.append((request.full_url, json.loads(request.data.decode("utf-8")), timeout))
        return _Response({
            "choices": [{"message": {"content": '{"ok": true}'}}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
        })

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    usage = []
    client = QwenClient("https://dashscope.example/v1", "secret-value", "qwen-plus", usage_callback=usage.append)

    result = client.complete_json([{"role": "user", "content": "ping"}], usage_kind="strategic")

    assert result == {"ok": True}
    assert calls[0][0] == "https://dashscope.example/v1/chat/completions"
    assert calls[0][1]["model"] == "qwen-plus"
    assert usage == [{"kind": "strategic", "model": "qwen-plus", "prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}]


def test_qwen_image_request_is_an_image_url_content_part(monkeypatch) -> None:
    captured = {}

    def fake_urlopen(request, timeout):
        captured.update(json.loads(request.data.decode("utf-8")))
        return _Response({"choices": [{"message": {"content": "{}"}}]})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    QwenClient("https://example.test/v1", "key", "vision").analyze_image_json(b"png", "inspect")

    content = captured["messages"][1]["content"]
    assert content[0] == {"type": "text", "text": "inspect"}
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_runtime_telemetry_accepts_verified_state(monkeypatch) -> None:
    now = datetime.now(timezone.utc).isoformat()
    responses = {
        "/health": {"source": "runtime_bridge", "status": "OK"},
        "/state": {
            "source": "runtime_bridge",
            "status": "OK",
            "game_pid": 26320,
            "game_version": "1.0.0",
            "observed_at": now,
            "city_name": "新的城市",
            "year": 1,
            "month": 4,
            "gold": 1000,
            "population": 10,
            "resources": {},
            "buildings_count": 1,
            "sites_count": 0,
            "build_menu_open": False,
        },
    }

    def fake_urlopen(request, timeout):
        path = request.full_url.rsplit("/", 1)[-1]
        return _Response(responses[f"/{path}"])

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    observation = RuntimeTelemetryClient(expected_pid=26320, expected_game_version="1.0.0").observe()

    assert observation.source == "runtime-telemetry"
    assert observation.data["population"] == 10


def test_runtime_telemetry_rejects_unknown_state(monkeypatch) -> None:
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, timeout: _Response({"source": "runtime_bridge", "status": "UNKNOWN"}),
    )

    with pytest.raises(RuntimeTelemetrySchemaError, match="UNKNOWN"):
        RuntimeTelemetryClient().read()


def test_runtime_telemetry_rejects_incomplete_ok_state(monkeypatch) -> None:
    now = datetime.now(timezone.utc).isoformat()
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, timeout: _Response({
            "source": "runtime_bridge",
            "status": "OK",
            "game_pid": 1,
            "game_version": "1.0.0",
            "observed_at": now,
            "gold": 1000,
        }),
    )

    with pytest.raises(RuntimeTelemetrySchemaError, match="missing fields"):
        RuntimeTelemetryClient().read()


def test_runtime_telemetry_rejects_process_version_and_stale_snapshot(monkeypatch) -> None:
    now = datetime.now(timezone.utc).isoformat()
    base = {
        "source": "runtime_bridge",
        "status": "OK",
        "game_pid": 1,
        "game_version": "old",
        "observed_at": now,
        "city_name": "新的城市",
        "year": 1,
        "month": 4,
        "gold": 1000,
        "population": 10,
        "resources": {},
        "buildings_count": 1,
        "sites_count": 0,
        "build_menu_open": False,
    }

    monkeypatch.setattr("urllib.request.urlopen", lambda request, timeout: _Response(base))
    with pytest.raises(RuntimeTelemetrySchemaError, match="RUNTIME_PROCESS_CHANGED"):
        RuntimeTelemetryClient(expected_pid=2).read()
    with pytest.raises(RuntimeTelemetrySchemaError, match="RUNTIME_VERSION_MISMATCH"):
        RuntimeTelemetryClient(expected_game_version="new").read()

    stale = dict(base, observed_at="2000-01-01T00:00:00+00:00")
    monkeypatch.setattr("urllib.request.urlopen", lambda request, timeout: _Response(stale))
    with pytest.raises(RuntimeTelemetrySchemaError, match="RUNTIME_STALE"):
        RuntimeTelemetryClient().read()
