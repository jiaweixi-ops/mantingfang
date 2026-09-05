from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from typing import Any


class DeepSeekConfigurationError(RuntimeError):
    pass


class DeepSeekRequestError(RuntimeError):
    pass


class DeepSeekClient:
    """Small standard-library client for DeepSeek-compatible chat completions."""

    def __init__(self, api_base: str, api_key: str | None, default_model: str | None = None, timeout: int = 60) -> None:
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.default_model = default_model
        self.timeout = timeout

    def complete_json(self, messages: list[dict[str, Any]], *, model: str | None = None, temperature: float = 0) -> dict[str, Any]:
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
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise DeepSeekRequestError(str(exc)) from exc
        try:
            content = body["choices"][0]["message"]["content"]
            if isinstance(content, dict):
                return content
            return json.loads(content)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise DeepSeekRequestError("DeepSeek returned a non-JSON response") from exc

    def analyze_image_json(self, image: bytes, prompt: str, *, model: str | None = None) -> dict[str, Any]:
        encoded = base64.b64encode(image).decode("ascii")
        return self.complete_json([
            {"role": "system", "content": "你是满庭芳游戏的视觉状态读取器，只报告图像中可确认的事实。"},
            {"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded}"}},
            ]},
        ], model=model)
