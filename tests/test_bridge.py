import json
import threading
import io
import time
from pathlib import Path

from codeagent.bridge import Bridge
from codeagent.agent import Event
from codeagent.config import Settings
from conftest import FakeLLM, covered_script, reply, tool_call

class BridgeForTesting(Bridge):
    def __init__(self):
        super().__init__()
        self.sent_messages = []
        self._running = True

    def _send(self, data: dict):
        with self.lock:
            self.sent_messages.append(data)


def test_bridge_request_response_and_unknown_method():
    bridge = BridgeForTesting()
    bridge.handle_request({"id": 1, "method": "unknown_method"})
    assert len(bridge.sent_messages) == 1
    assert bridge.sent_messages[0]["id"] == 1
    assert "error" in bridge.sent_messages[0]
    assert "Unknown method" in bridge.sent_messages[0]["error"]

def test_bridge_settings_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    
    bridge = BridgeForTesting()
    bridge.handle_save_settings(2, {"provider": "gemini", "base_url": "http://test", "max_turns": 42})
    assert bridge.sent_messages[-1] == {"id": 2, "result": "ok"}
    
    bridge.handle_get_settings(3, {})
    res = bridge.sent_messages[-1]
    assert res["id"] == 3
    assert res["result"]["provider"] == "gemini"
    assert res["result"]["base_url"] == "http://test"
    assert res["result"]["max_turns"] == 42


def test_bridge_start_run_streaming(tmp_path, sample_inputs):
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    
    bridge = BridgeForTesting()
    bridge.test_llm = FakeLLM(covered_script())
    
    settings = {
        "input_files": [str(p) for p in sample_inputs],
        "output_dir": str(out_dir),
        "api_key": "test_key",
        "provider": "deepseek"
    }
    bridge.handle_start_run(10, {"settings": settings})
    assert bridge.sent_messages[-1] == {"id": 10, "result": "started"}
    
    # wait for the worker thread to finish
    bridge.worker_thread.join(timeout=10)
    
    events = [msg for msg in bridge.sent_messages if "event" in msg]
    kinds = [e["event"] for e in events]
    assert "status" in kinds
    assert "tool_call" in kinds
    assert "done" in kinds
    
    done_event = next(e for e in events if e["event"] == "done")
    assert done_event["data"]["success"] is True
    


def test_bridge_stop_run():
    bridge = BridgeForTesting()
    
    def fake_work():
        while not bridge.cancel_event.is_set():
            time.sleep(0.01)
            
    bridge.worker_thread = threading.Thread(target=fake_work, daemon=True)
    bridge.worker_thread.start()
    
    bridge.handle_stop_run(20, {})
    assert bridge.sent_messages[-1] == {"id": 20, "result": "stopping"}
    
    bridge.worker_thread.join(timeout=2)
    assert not bridge.worker_thread.is_alive()


def test_bridge_emits_exactly_one_done(tmp_path, sample_inputs):
    bridge = BridgeForTesting()
    bridge.test_llm = FakeLLM(covered_script())
    bridge.handle_start_run(1, {"settings": {"input_files": [str(p) for p in sample_inputs],
                                             "output_dir": str(tmp_path / "o"), "api_key": "k"}})
    bridge.worker_thread.join(timeout=10)
    dones = [m for m in bridge.sent_messages if m.get("event") == "done"]
    assert len(dones) == 1 and dones[0]["data"]["success"] is True


def test_bridge_subprocess_protocol(tmp_path):
    """The real `codeagent bridge` process must answer on stdout with protocol JSON only."""
    import os
    import subprocess
    import sys
    root = Path(__file__).resolve().parents[1]
    env = {**os.environ, "PYTHONPATH": str(root / "src"), "APPDATA": str(tmp_path), "XDG_CONFIG_HOME": str(tmp_path)}
    proc = subprocess.run(
        [sys.executable, "-m", "codeagent", "bridge"],
        input='{"id": 7, "method": "list_samples", "params": {}}\n{"id": 8, "method": "nope"}\n',
        capture_output=True, text=True, timeout=30, env=env,
    )
    lines = [json.loads(l) for l in proc.stdout.splitlines() if l.strip()]
    assert lines[0]["id"] == 7 and len(lines[0]["result"]) == 2
    assert lines[1]["id"] == 8 and "Unknown method" in lines[1]["error"]
