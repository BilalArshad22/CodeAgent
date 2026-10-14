"""Minimal DeepSeek chat-completions client (OpenAI-compatible wire format).

Only the standard library is used so the frozen .exe stays small and has no
native dependencies. Thinking mode is DeepSeek's default; when it is on, the
API requires every assistant message's ``reasoning_content`` to be sent back
on later requests, so the client returns it as part of the message dict and
the agent keeps it in history untouched.
"""

from __future__ import annotations

import json
import re
import socket
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable

RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504}


class LLMError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class Cancelled(RuntimeError):
    pass


@dataclass
class LLMResponse:
    message: dict[str, Any]
    finish_reason: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)


class DeepSeekClient:
    """OpenAI-compatible chat client. ``provider`` is "deepseek" (default) or "gemini" (testing only)."""

    def __init__(
        self,
        api_key: str,
        model: str = "deepseek-v4-pro",
        base_url: str = "https://api.deepseek.com",
        thinking: bool = True,
        max_tokens: int = 32000,
        timeout: float = 900.0,
        max_retries: int = 5,
        cancel_event: threading.Event | None = None,
        urlopen: Callable[..., Any] = urllib.request.urlopen,
        sleep: Callable[[float], None] | None = None,
        provider: str = "deepseek",
        on_retry: Callable[[str], None] | None = None,
    ):
        if not api_key:
            raise LLMError(f"{'Gemini' if provider == 'gemini' else 'DeepSeek'} API key is not set.")
        self.provider = provider
        self.on_retry = on_retry
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.thinking = thinking
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.max_retries = max_retries
        self.cancel_event = cancel_event or threading.Event()
        self._urlopen = urlopen
        self._sleep = sleep or self._interruptible_sleep

    # ------------------------------------------------------------------ public
    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> LLMResponse:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": self.max_tokens,
            "stream": False,
        }
        if self.provider == "gemini":
            if not self.thinking:
                body["reasoning_effort"] = "low"
        elif "chat" not in self.model:
            body["thinking"] = {"type": "enabled" if self.thinking else "disabled"}
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        data = self._request("POST", "/chat/completions", body)
        try:
            choice = data["choices"][0]
            raw = choice["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"Unexpected response shape: {str(data)[:500]}") from exc
        return LLMResponse(
            message=self._normalise_message(raw),
            finish_reason=choice.get("finish_reason"),
            usage=data.get("usage") or {},
        )

    def list_models(self) -> list[str]:
        data = self._request("GET", "/models", None)
        return [m.get("id", "").removeprefix("models/") for m in data.get("data", [])]

    # ---------------------------------------------------------------- helpers
    @staticmethod
    def _normalise_message(raw: dict) -> dict:
        msg: dict[str, Any] = {"role": "assistant", "content": raw.get("content") or ""}
        if raw.get("reasoning_content"):
            msg["reasoning_content"] = raw["reasoning_content"]
        if raw.get("extra_content"):
            msg["extra_content"] = raw["extra_content"]
        if raw.get("tool_calls"):
            calls = []
            for tc in raw["tool_calls"]:
                call = {
                    "id": tc.get("id"),
                    "type": "function",
                    "function": {
                        "name": tc.get("function", {}).get("name", ""),
                        "arguments": tc.get("function", {}).get("arguments") or "{}",
                    },
                }
                # Provider-specific data (e.g. Gemini thought signatures) must round-trip untouched.
                if tc.get("extra_content"):
                    call["extra_content"] = tc["extra_content"]
                calls.append(call)
            msg["tool_calls"] = calls
        return msg

    def _send(self, req: urllib.request.Request) -> bytes:
        """Perform the HTTP call on a helper thread so Stop takes effect immediately.

        urllib cannot abort a request in progress, and a slow model call can take minutes.
        On cancel the helper thread is abandoned (daemon); its eventual result is discarded.
        """
        box: dict[str, Any] = {}

        def target() -> None:
            try:
                with self._urlopen(req, timeout=self.timeout) as resp:
                    box["body"] = resp.read()
            except BaseException as exc:  # re-raised on the calling thread
                box["error"] = exc

        worker = threading.Thread(target=target, name="llm-request", daemon=True)
        worker.start()
        while worker.is_alive():
            if self.cancel_event.wait(0.1):
                raise Cancelled("Cancelled by user.")
        if "error" in box:
            raise box["error"]
        return box["body"]

    def _interruptible_sleep(self, seconds: float) -> None:
        if self.cancel_event.wait(seconds):
            raise Cancelled("Cancelled by user.")

    def _request(self, method: str, path: str, body: dict | None) -> dict:
        url = self.base_url + path
        payload = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }
        if payload is not None:
            headers["Content-Type"] = "application/json"

        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            if self.cancel_event.is_set():
                raise Cancelled("Cancelled by user.")
            req = urllib.request.Request(url, data=payload, headers=headers, method=method)
            try:
                return json.loads(self._send(req).decode("utf-8"))
            except urllib.error.HTTPError as exc:
                detail = _read_error_body(exc)
                if exc.code in (401, 403):
                    raise LLMError(f"Authentication failed ({exc.code}): {detail}", exc.code) from exc
                if exc.code not in RETRYABLE_STATUS:
                    raise LLMError(f"HTTP {exc.code}: {detail}", exc.code) from exc
                last_error = LLMError(f"HTTP {exc.code}: {detail}", exc.code)
                retry_after = _retry_after(exc, detail)
            except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError) as exc:
                last_error = LLMError(f"Network error: {exc}")
                retry_after = None
            except ValueError as exc:
                last_error = LLMError(f"Invalid JSON from API: {exc}")
                retry_after = None
            if attempt < self.max_retries:
                delay = retry_after if retry_after is not None else min(60.0, 2.0 ** (attempt + 1))
                if self.on_retry:
                    self.on_retry(f"{last_error} - retrying in {delay:.0f}s "
                                  f"(attempt {attempt + 2}/{self.max_retries + 1})")
                self._sleep(delay)
        assert last_error is not None
        raise last_error


def _read_error_body(exc: urllib.error.HTTPError) -> str:
    try:
        text = exc.read().decode("utf-8", "replace")
    except Exception:
        return exc.reason or ""
    try:
        return json.loads(text).get("error", {}).get("message") or text[:500]
    except (ValueError, AttributeError):
        return text[:500]


def _retry_after(exc: urllib.error.HTTPError, error_body: str = "") -> float | None:
    value = exc.headers.get("Retry-After") if exc.headers else None
    if value:
        try:
            return min(120.0, float(value))
        except ValueError:
            pass
    # Extract "Please retry in X.XXs" from Google/provider error response
    if error_body:
        match = re.search(r"retry in (\d+(?:\.\d+)?)s", error_body, re.I)
        if match:
            try:
                return min(120.0, float(match.group(1)) + 0.5)
            except ValueError:
                pass
    return None
