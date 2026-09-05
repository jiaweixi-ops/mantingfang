from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Protocol

from .feishu import CommandRouter, FeishuTransport


class FeishuApiError(RuntimeError):
    pass


class HttpTransport(Protocol):
    def request(self, method: str, url: str, headers: dict[str, str], body: bytes) -> tuple[int, bytes]: ...


class UrllibHttpTransport:
    def request(self, method: str, url: str, headers: dict[str, str], body: bytes) -> tuple[int, bytes]:
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()
        except urllib.error.URLError as exc:
            raise FeishuApiError(str(exc)) from exc


@dataclass
class FeishuApiClient:
    app_id: str
    app_secret: str
    api_base: str = "https://open.feishu.cn"
    http: HttpTransport | None = None

    def __post_init__(self) -> None:
        if not self.app_id or not self.app_secret:
            raise ValueError("Feishu app_id and app_secret are required")
        self.api_base = self.api_base.rstrip("/")
        self.http = self.http or UrllibHttpTransport()
        self._tenant_token: str | None = None
        self._tenant_token_expires_at = 0.0

    def tenant_access_token(self) -> str:
        if self._tenant_token and time.time() < self._tenant_token_expires_at:
            return self._tenant_token
        payload = self._json_request(
            "POST",
            "/open-apis/auth/v3/tenant_access_token/internal",
            {},
            {"app_id": self.app_id, "app_secret": self.app_secret},
        )
        token = payload.get("tenant_access_token")
        if payload.get("code") != 0 or not isinstance(token, str) or not token:
            raise FeishuApiError(f"Feishu token request failed: {payload}")
        self._tenant_token = token
        self._tenant_token_expires_at = time.time() + max(1, int(payload.get("expire", 7200)) - 60)
        return token

    def send_text(self, receive_id: str, text: str, *, receive_id_type: str = "chat_id") -> dict[str, Any]:
        if not receive_id:
            raise ValueError("receive_id is required")
        return self._json_request(
            "POST",
            f"/open-apis/im/v1/messages?receive_id_type={receive_id_type}",
            {"Authorization": f"Bearer {self.tenant_access_token()}"},
            {"receive_id": receive_id, "msg_type": "text", "content": json.dumps({"text": text}, ensure_ascii=False)},
        )

    def _json_request(self, method: str, path: str, extra_headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
        headers = {"Content-Type": "application/json; charset=utf-8", **extra_headers}
        status, raw = self.http.request(method, f"{self.api_base}{path}", headers, json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        try:
            result = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise FeishuApiError(f"Feishu returned invalid JSON (HTTP {status})") from exc
        if status >= 400:
            raise FeishuApiError(f"Feishu HTTP {status}: {result}")
        return result


@dataclass
class FeishuHttpTransport:
    client: FeishuApiClient
    receive_id: str
    receive_id_type: str = "chat_id"

    def send_text(self, text: str) -> None:
        self.client.send_text(self.receive_id, text, receive_id_type=self.receive_id_type)


@dataclass
class FeishuEventHandler:
    router: CommandRouter
    client: FeishuApiClient
    verification_token: str | None = None
    encrypt_key: str | None = None

    def handle(self, payload: dict[str, Any], *, raw_body: bytes | None = None, headers: dict[str, str] | None = None) -> dict[str, Any]:
        if self.encrypt_key and raw_body is not None and headers:
            self._verify_signature(raw_body, headers)
        if payload.get("type") == "url_verification":
            if self.verification_token and payload.get("token") != self.verification_token:
                raise FeishuApiError("Feishu verification token mismatch")
            return {"challenge": payload.get("challenge", "")}
        header = payload.get("header", {})
        if header.get("event_type") != "im.message.receive_v1":
            return {"ok": True, "ignored": True}
        event = payload.get("event", {})
        message = event.get("message", {})
        if message.get("message_type") != "text":
            return {"ok": True, "ignored": True}
        try:
            content = json.loads(message.get("content", "{}"))
        except json.JSONDecodeError as exc:
            raise FeishuApiError("Feishu message content is not JSON") from exc
        text = content.get("text")
        receive_id = message.get("chat_id") or message.get("open_chat_id")
        if not isinstance(text, str) or not isinstance(receive_id, str):
            raise FeishuApiError("Feishu text event lacks text or chat_id")
        response = self.router.handle(text)
        self.client.send_text(receive_id, response)
        return {"ok": True, "response": response}

    def _verify_signature(self, raw_body: bytes, headers: dict[str, str]) -> None:
        timestamp = headers.get("X-Lark-Request-Timestamp", "")
        nonce = headers.get("X-Lark-Request-Nonce", "")
        signature = headers.get("X-Lark-Signature", "")
        expected = sha256((timestamp + nonce + self.encrypt_key + raw_body.decode("utf-8")).encode("utf-8")).hexdigest()
        if not signature or signature != expected:
            raise FeishuApiError("Feishu event signature mismatch")
