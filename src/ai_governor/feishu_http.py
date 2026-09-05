from __future__ import annotations

import json
import base64
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

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

    def upload_image(self, image_path: str | Path) -> str:
        path = Path(image_path)
        if not path.is_file():
            raise FeishuApiError(f"Feishu image file not found: {path}")
        boundary = f"----CodexFeishu{uuid4().hex}"
        image = path.read_bytes()
        body = b"".join([
            f"--{boundary}\r\n".encode(),
            b'Content-Disposition: form-data; name="image_type"\r\n\r\nmessage\r\n',
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="image"; filename="{path.name}"\r\n'.encode(),
            b"Content-Type: image/png\r\n\r\n",
            image,
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ])
        status, raw = self.http.request(
            "POST",
            f"{self.api_base}/open-apis/im/v1/images",
            {
                "Authorization": f"Bearer {self.tenant_access_token()}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
            body,
        )
        result = self._decode_response(status, raw)
        image_key = result.get("data", {}).get("image_key")
        if result.get("code") != 0 or not isinstance(image_key, str) or not image_key:
            raise FeishuApiError(f"Feishu image upload failed: {result}")
        return image_key

    def send_image(self, receive_id: str, image_path: str | Path, *, receive_id_type: str = "chat_id") -> dict[str, Any]:
        image_key = self.upload_image(image_path)
        return self._json_request(
            "POST",
            f"/open-apis/im/v1/messages?receive_id_type={receive_id_type}",
            {"Authorization": f"Bearer {self.tenant_access_token()}"},
            {"receive_id": receive_id, "msg_type": "image", "content": json.dumps({"image_key": image_key})},
        )

    def _json_request(self, method: str, path: str, extra_headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
        headers = {"Content-Type": "application/json; charset=utf-8", **extra_headers}
        status, raw = self.http.request(method, f"{self.api_base}{path}", headers, json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        return self._decode_response(status, raw)

    @staticmethod
    def _decode_response(status: int, raw: bytes) -> dict[str, Any]:
        try:
            result = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise FeishuApiError(f"Feishu returned invalid JSON (HTTP {status})") from exc
        if not isinstance(result, dict):
            raise FeishuApiError(f"Feishu returned a non-object response (HTTP {status})")
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

    def send_image(self, image_path: str) -> None:
        self.client.send_image(self.receive_id, image_path, receive_id_type=self.receive_id_type)


@dataclass
class FeishuEventHandler:
    router: CommandRouter
    client: FeishuApiClient
    verification_token: str | None = None
    encrypt_key: str | None = None

    def handle(self, payload: dict[str, Any], *, raw_body: bytes | None = None, headers: dict[str, str] | None = None) -> dict[str, Any]:
        if self.encrypt_key and raw_body is not None and headers:
            self._verify_signature(raw_body, headers)
        if "encrypt" in payload:
            if not self.encrypt_key:
                raise FeishuApiError("encrypted Feishu callback requires FEISHU_ENCRYPT_KEY")
            payload = FeishuPayloadCipher.decrypt(str(payload["encrypt"]), self.encrypt_key)
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
        if not signature or not hmac.compare_digest(signature, expected):
            raise FeishuApiError("Feishu event signature mismatch")


class FeishuPayloadCipher:
    """Decrypt Feishu encrypted callback payloads using the configured Encrypt Key."""

    @staticmethod
    def decrypt(encoded: str, encrypt_key: str) -> dict[str, Any]:
        try:
            from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        except ImportError as exc:
            raise FeishuApiError("encrypted callbacks require the optional 'cryptography' package") from exc
        try:
            key = hashlib.sha256(encrypt_key.encode("utf-8")).digest()
            cipher = Cipher(algorithms.AES(key), modes.CBC(key[:16]))
            decryptor = cipher.decryptor()
            padded = decryptor.update(base64.b64decode(encoded)) + decryptor.finalize()
            padding = padded[-1]
            if padding < 1 or padding > 16 or padded[-padding:] != bytes([padding]) * padding:
                raise ValueError("invalid PKCS7 padding")
            payload = json.loads(padded[:-padding].decode("utf-8"))
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise FeishuApiError("Feishu encrypted callback could not be decrypted") from exc
        if not isinstance(payload, dict):
            raise FeishuApiError("Feishu decrypted callback must be a JSON object")
        return payload


class FeishuCallbackServer:
    """Small stdlib callback server for a Feishu custom app."""

    def __init__(self, event_handler: FeishuEventHandler, host: str = "127.0.0.1", port: int = 8787) -> None:
        self.event_handler = event_handler
        self.server = self._build_server(host, port)

    def _build_server(self, host: str, port: int) -> ThreadingHTTPServer:
        event_handler = self.event_handler

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length", "0"))
                raw_body = self.rfile.read(length)
                try:
                    payload = json.loads(raw_body.decode("utf-8"))
                    result = event_handler.handle(payload, raw_body=raw_body, headers=dict(self.headers.items()))
                    body = json.dumps(result, ensure_ascii=False).encode("utf-8")
                    status = 200
                except (FeishuApiError, json.JSONDecodeError, ValueError) as exc:
                    body = json.dumps({"error": str(exc)}, ensure_ascii=False).encode("utf-8")
                    status = 400
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: Any) -> None:
                return

        return ThreadingHTTPServer((host, port), Handler)

    @property
    def address(self) -> tuple[str, int]:
        return self.server.server_address

    def serve_forever(self) -> None:
        self.server.serve_forever()

    def shutdown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
