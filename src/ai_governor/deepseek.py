from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


class DeepSeekConfigurationError(RuntimeError):
    pass


class DeepSeekRequestError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, error_type: str | None = None) -> None:
        self.status_code = status_code
        self.error_type = error_type
        super().__init__(message)


@dataclass(frozen=True)
class DeepSeekUsage:
    kind: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "model": self.model,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }


class DeepSeekClient:
    """Small standard-library client for DeepSeek-compatible chat completions."""

    def __init__(
        self,
        api_base: str,
        api_key: str | None,
        default_model: str | None = None,
        timeout: int = 60,
        max_retries: int = 2,
        backoff_seconds: float = 1.0,
        sleep_fn: Any = time.sleep,
        usage_callback: Any = None,
    ) -> None:
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.default_model = default_model
        self.timeout = timeout
        if max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        if backoff_seconds < 0:
            raise ValueError("backoff_seconds must be non-negative")
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self.sleep_fn = sleep_fn
        self.usage_callback = usage_callback
        self.usage_totals = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        self.last_usage: DeepSeekUsage | None = None

    def complete_json(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        temperature: float = 0,
        usage_kind: str = "chat",
    ) -> dict[str, Any]:
        if not self.api_key:
            raise DeepSeekConfigurationError("DEEPSEEK_API_KEY is not configured")
        chosen_model = model or self.default_model
        if not chosen_model:
            raise DeepSeekConfigurationError("a DeepSeek model must be configured")
        payload = {
            "model": chosen_model,
            "messages": messages,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }
        request = urllib.request.Request(
            f"{self.api_base}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        body: dict[str, Any] | None = None
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    body = json.loads(response.read().decode("utf-8"))
                break
            except urllib.error.HTTPError as exc:
                last_error = exc
                retryable = exc.code == 408 or exc.code == 429 or 500 <= exc.code <= 599
                if not retryable or attempt >= self.max_retries:
                    detail = exc.read().decode("utf-8", errors="replace")
                    if self.api_key:
                        detail = detail.replace(self.api_key, "[REDACTED]")
                    raise DeepSeekRequestError(
                        f"DeepSeek HTTP {exc.code}: {detail}",
                        status_code=exc.code,
                        error_type="http_error",
                    ) from exc
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    raise DeepSeekRequestError(str(exc), error_type=type(exc).__name__) from exc
            self.sleep_fn(self.backoff_seconds * (2 ** attempt))
        if body is None:
            raise DeepSeekRequestError(str(last_error or "DeepSeek request failed"), error_type="request_failed")
        self._record_usage(body.get("usage"), chosen_model, usage_kind)
        try:
            content = body["choices"][0]["message"]["content"]
            if isinstance(content, dict):
                return content
            return json.loads(content)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise DeepSeekRequestError("DeepSeek returned a non-JSON response", error_type="invalid_json") from exc

    def analyze_image_json(self, image: bytes, prompt: str, *, model: str | None = None) -> dict[str, Any]:
        encoded = base64.b64encode(image).decode("ascii")
        return self.complete_json([
            {"role": "system", "content": "你是满庭芳游戏的视觉状态读取器，只报告图像中可确认的事实。"},
            {"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded}"}},
            ]},
        ], model=model, usage_kind="vision")

    def _record_usage(self, raw: Any, model: str, kind: str) -> None:
        if not isinstance(raw, dict):
            return
        usage = DeepSeekUsage(
            kind=kind,
            model=model,
            prompt_tokens=int(raw.get("prompt_tokens", 0) or 0),
            completion_tokens=int(raw.get("completion_tokens", 0) or 0),
            total_tokens=int(raw.get("total_tokens", 0) or 0),
        )
        self.last_usage = usage
        for key in self.usage_totals:
            self.usage_totals[key] += getattr(usage, key)
        if self.usage_callback is not None:
            self.usage_callback(usage.to_dict())
