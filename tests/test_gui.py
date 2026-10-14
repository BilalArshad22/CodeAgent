import tkinter as tk
import pytest
from codeagent.agent import Event

@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display available")
    root.withdraw()
    from codeagent.gui import App
    a = App(root)
    yield a
    root.destroy()

def test_gui_builds_and_handles_events(app):
    app.use_samples()
    assert app.files.size() == 2
    app._handle_event(Event("todos", data={"todos": [{"id": "1", "content": "a", "status": "completed"},
                                                     {"id": "2", "content": "b", "status": "pending"}]}))
    assert len(app.plan.get_children()) == 2
    
    app._handle_event(Event("usage", data={"requests": 1, "prompt_tokens": 10, "completion_tokens": 5,
                                           "cache_hit_tokens": 2}))
    assert "↓" in app.usage_text.get()
    
    app._handle_event(Event("tool_call", "write_file src/a.js", data={"name": "write_file", "args": {"path": "src/a.js"}}))
    assert "Write" in app.log.get("1.0", "end")
    assert "src/a.js" in app.log.get("1.0", "end")
    s = app._collect_settings()
    assert s.input_files and s.output_dir

def test_gui_provider_switch_keeps_keys_separate(app):
    from codeagent.config import PROVIDERS
    app.api_key.set("sk-deepseek")
    app.provider_label.set(PROVIDERS["gemini"]["label"])
    app._provider_changed()
    assert app.api_key.get() == "" and app.model.get().startswith("gemini")
    assert "Testing only" in app.provider_warning.cget("text")
    app.api_key.set("g-key")
    s = app._collect_settings()
    assert (s.provider, s.api_key, s.gemini_api_key) == ("gemini", "sk-deepseek", "g-key")
    app.provider_label.set(PROVIDERS["deepseek"]["label"])
    app._provider_changed()
    assert app.api_key.get() == "sk-deepseek" and app.model.get() == "deepseek-v4-pro"
    assert app.provider_warning.cget("text") == ""

def test_gui_cost_calculation(app):
    app.provider_key = "deepseek"
    app.settings.model = "deepseek-v4-pro"
    app._handle_event(Event("usage", data={"requests": 1, "prompt_tokens": 1000000, "completion_tokens": 1000000, "cache_hit_tokens": 500000}))
    # miss = 500k = $0.66
    # hit = 500k = $0.022
    # out = 1M = $3.96
    # total = 4.642
    assert abs(app.total_cost - 4.642) < 0.01

def test_gui_cost_calculation_flash(app):
    app.provider_key = "deepseek"
    app.settings.model = "deepseek-flash"
    app._handle_event(Event("usage", data={"requests": 1, "prompt_tokens": 1000000, "completion_tokens": 1000000, "cache_hit_tokens": 500000}))
    # miss = 500k = $0.15
    # hit = 500k = $0.003
    # out = 1M = $1.20
    # total = 1.353
    assert abs(app.total_cost - 1.353) < 0.01
