import io
import json
import urllib.error

import pytest

from codeagent.config import Settings, load_settings, save_settings
from codeagent.llm import DeepSeekClient, LLMError


class FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def http_error(code, body=b'{"error": {"message": "boom"}}', headers=None):
    return urllib.error.HTTPError("https://x", code, "err", headers or {}, io.BytesIO(body))


def make_client(responses, **kw):
    calls = []

    def urlopen(req, timeout):
        calls.append(req)
        r = responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return FakeResp(json.dumps(r).encode())

    client = DeepSeekClient("sk-test", urlopen=urlopen, sleep=lambda s: None, **kw)
    return client, calls


OK = {"choices": [{"finish_reason": "tool_calls", "message": {
    "role": "assistant", "content": None, "reasoning_content": "hmm",
    "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "list_files", "arguments": "{}"}}]}}],
    "usage": {"prompt_tokens": 5, "completion_tokens": 7}}


def test_chat_request_and_normalisation():
    client, calls = make_client([OK], thinking=False, model="deepseek-v4-pro")
    resp = client.chat([{"role": "user", "content": "hi"}], tools=[{"type": "function"}])
    body = json.loads(calls[0].data)
    assert calls[0].full_url == "https://api.deepseek.com/chat/completions"
    assert calls[0].get_header("Authorization") == "Bearer sk-test"
    assert body["model"] == "deepseek-v4-pro" and body["thinking"] == {"type": "disabled"}
    assert body["tool_choice"] == "auto"
    assert resp.message == {"role": "assistant", "content": "", "reasoning_content": "hmm",
                            "tool_calls": [{"id": "c1", "type": "function",
                                            "function": {"name": "list_files", "arguments": "{}"}}]}
    assert resp.finish_reason == "tool_calls" and resp.usage["completion_tokens"] == 7


def test_retries_on_429_and_5xx_then_succeeds():
    client, calls = make_client([http_error(429), http_error(503), urllib.error.URLError("down"), OK])
    assert client.chat([]).message["reasoning_content"] == "hmm"
    assert len(calls) == 4


def test_auth_error_not_retried():
    client, calls = make_client([http_error(401), OK])
    with pytest.raises(LLMError, match="Authentication failed"):
        client.chat([])
    assert len(calls) == 1


def test_bad_request_surfaces_message():
    client, _ = make_client([http_error(400)])
    with pytest.raises(LLMError, match="HTTP 400: boom"):
        client.chat([])


def test_gives_up_after_max_retries():
    client, calls = make_client([http_error(500)] * 3, max_retries=2)
    with pytest.raises(LLMError, match="HTTP 500"):
        client.chat([])
    assert len(calls) == 3


def test_missing_key():
    with pytest.raises(LLMError):
        DeepSeekClient("")


def test_list_models():
    client, calls = make_client([{"data": [{"id": "deepseek-v4-pro"}, {"id": "deepseek-flash"}]}])
    assert client.list_models() == ["deepseek-v4-pro", "deepseek-flash"]
    assert calls[0].get_method() == "GET"


def test_settings_roundtrip(tmp_path, monkeypatch):
    path = tmp_path / "s.json"
    save_settings(Settings(api_key="sk-1", model="m", input_files=["a.md"]), path)
    s = load_settings(path)
    assert (s.api_key, s.model, s.input_files) == ("sk-1", "m", ["a.md"])

    save_settings(Settings(api_key="sk-1", remember_key=False), path)
    assert load_settings(path).api_key == ""

    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-env")
    assert Settings().effective_api_key() == "sk-env"
    path.write_text("{corrupt")
    assert load_settings(path) == Settings()


def test_gemini_request_shape_and_extra_content_roundtrip():
    gem = {"choices": [{"finish_reason": "tool_calls", "message": {
        "role": "assistant", "content": "",
        "tool_calls": [{"id": "g1", "type": "function", "extra_content": {"google": {"thought_signature": "sig"}},
                        "function": {"name": "list_files", "arguments": "{}"}}]}}]}
    client, calls = make_client([gem, gem], provider="gemini", thinking=True,
                                base_url="https://generativelanguage.googleapis.com/v1beta/openai/")
    resp = client.chat([{"role": "user", "content": "hi"}])
    body = json.loads(calls[0].data)
    assert calls[0].full_url == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    assert "thinking" not in body and "reasoning_effort" not in body
    assert resp.message["tool_calls"][0]["extra_content"] == {"google": {"thought_signature": "sig"}}

    client.thinking = False
    client.chat([])
    assert json.loads(calls[1].data)["reasoning_effort"] == "low"


def test_gemini_model_ids_are_unprefixed():
    client, _ = make_client([{"data": [{"id": "models/gemini-3.8-flash"}]}], provider="gemini")
    assert client.list_models() == ["gemini-3.8-flash"]


def test_provider_key_selection(monkeypatch):
    for var in ("DEEPSEEK_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    s = Settings(api_key="sk-ds", gemini_api_key="g-key")
    assert s.effective_api_key() == "sk-ds"
    s.provider = "gemini"
    assert s.effective_api_key() == "g-key"
    s.gemini_api_key = ""
    monkeypatch.setenv("GOOGLE_API_KEY", "g-env")
    assert s.effective_api_key() == "g-env"


def test_retries_are_reported():
    seen = []
    client, _ = make_client([http_error(429, headers={"Retry-After": "7"}), OK], on_retry=seen.append)
    client.chat([])
    assert len(seen) == 1 and "HTTP 429" in seen[0] and "retrying in 7s" in seen[0] and "attempt 2/" in seen[0]


def test_stop_interrupts_in_flight_request():
    import threading
    import time
    from codeagent.llm import Cancelled
    cancel = threading.Event()
    release = threading.Event()

    def hanging_urlopen(req, timeout):
        release.wait(10)  # simulates a model call that takes minutes
        return FakeResp(json.dumps(OK).encode())

    client = DeepSeekClient("k", urlopen=hanging_urlopen, cancel_event=cancel)
    threading.Timer(0.2, cancel.set).start()
    start = time.monotonic()
    with pytest.raises(Cancelled):
        client.chat([])
    assert time.monotonic() - start < 2
    release.set()
