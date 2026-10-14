import json
import threading

from codeagent.agent import ELIDED, CodeAgent
from codeagent.config import Settings
from codeagent.runner import run_pipeline
from codeagent.tools import Workspace

from conftest import MINIMAL_PROJECT, FakeLLM, covered_script, reply, tool_call


def write_all():
    return [tool_call("write_file", {"path": p, "content": c}) for p, c in MINIMAL_PROJECT.items()]


def happy_script():
    return [
        reply(tool_call("todo_write", {"todos": [{"content": "write code", "status": "in_progress"}]}),
              reasoning="I should plan first."),
        reply(*write_all()),
        reply(tool_call("check_project", {})),
        reply(tool_call("todo_write", {"todos": [{"content": "write code", "status": "completed"}]}),
              tool_call("finish", {"summary": "Built demo."})),
    ]


def test_happy_path_writes_files_and_finishes(tmp_path):
    events = []
    ws = Workspace(tmp_path, spec={"summary": {}})
    llm = FakeLLM(happy_script())
    agent = CodeAgent(llm, ws, on_event=events.append)
    result = agent.run()

    assert result.success and result.stop_reason == "finished"
    assert result.summary == "Built demo."
    assert (tmp_path / "src/math.js").exists()
    assert result.usage["requests"] == 4 and result.usage["prompt_tokens"] == 400
    kinds = [e.kind for e in events]
    assert "todos" in kinds and "thinking" in kinds and kinds[-1] == "done"
    assert (tmp_path / ".codeagent/run_result.json").exists()
    assert len((tmp_path / ".codeagent/transcript.jsonl").read_text().splitlines()) == len(agent.messages)


def test_reasoning_content_is_sent_back(tmp_path):
    llm = FakeLLM(happy_script())
    CodeAgent(llm, Workspace(tmp_path, spec={})).run()
    second_request = llm.requests[1]
    assert second_request[2]["reasoning_content"] == "I should plan first."


def test_every_tool_call_gets_a_tool_message(tmp_path):
    llm = FakeLLM(happy_script())
    CodeAgent(llm, Workspace(tmp_path, spec={})).run()
    msgs = llm.requests[-1]
    for i, m in enumerate(msgs):
        for tc in m.get("tool_calls") or []:
            assert any(x.get("tool_call_id") == tc["id"] for x in msgs[i + 1:]), tc


def test_finish_is_rejected_until_project_is_valid(tmp_path):
    script = [
        reply(tool_call("finish", {"summary": "too early"})),
        reply(*write_all()),
        reply(tool_call("finish", {"summary": "now done"})),
    ]
    llm = FakeLLM(script)
    result = CodeAgent(llm, Workspace(tmp_path, spec={})).run()
    assert result.success and result.summary == "now done"
    rejection = llm.requests[1][-1]
    assert rejection["role"] == "tool" and "finish` rejected" in rejection["content"]


def test_finish_accepted_after_max_rejections_but_not_success(tmp_path):
    script = [reply(tool_call("finish", {"summary": f"try {i}"}, call_id=f"c{i}")) for i in range(5)]
    result = CodeAgent(FakeLLM(script), Workspace(tmp_path, spec={}), max_finish_rejections=2).run()
    assert result.stop_reason == "finished" and not result.success
    assert "Unresolved issues" in result.summary


def test_bad_json_arguments_are_reported_to_model(tmp_path):
    broken = {"id": "x1", "type": "function", "function": {"name": "write_file", "arguments": '{"path": "a.js", "con'}}
    llm = FakeLLM([reply(broken), *happy_script()])
    result = CodeAgent(llm, Workspace(tmp_path, spec={})).run()
    assert result.success
    assert "not valid JSON" in llm.requests[1][-1]["content"]


def test_tool_errors_do_not_stop_the_loop(tmp_path):
    llm = FakeLLM([reply(tool_call("read_file", {"path": "../../etc/passwd"})), *happy_script()])
    result = CodeAgent(llm, Workspace(tmp_path, spec={})).run()
    assert result.success
    assert llm.requests[1][-1]["content"].startswith("Error: path escapes")


def test_idle_model_is_nudged_then_stopped(tmp_path):
    script = [reply(content="thinking out loud", finish_reason="stop") for _ in range(10)]
    llm = FakeLLM(script)
    result = CodeAgent(llm, Workspace(tmp_path, spec={}), max_idle_nudges=2).run()
    assert result.stop_reason == "model_stopped" and result.turns == 3
    assert "not called `finish`" in llm.requests[1][-1]["content"]


def test_max_turns(tmp_path):
    script = [reply(tool_call("list_files", {}, call_id=f"l{i}")) for i in range(10)]
    result = CodeAgent(FakeLLM(script), Workspace(tmp_path, spec={}), max_turns=3).run()
    assert result.stop_reason == "max_turns" and result.turns == 3 and not result.success


def test_cancel(tmp_path):
    cancel = threading.Event()

    def cancel_then_reply(_):
        cancel.set()
        return reply(tool_call("list_files", {}))

    result = CodeAgent(FakeLLM([cancel_then_reply] * 3), Workspace(tmp_path, spec={}), cancel_event=cancel).run()
    assert result.stop_reason == "cancelled"


def test_compaction_elides_old_payloads_but_keeps_reasoning(tmp_path):
    big = "x" * 5000
    script = [reply(tool_call("write_file", {"path": f"f{i}.txt", "content": big}, call_id=f"w{i}"),
                    reasoning=f"r{i}") for i in range(8)]
    script.append(reply(*write_all()))
    script.append(reply(tool_call("finish", {"summary": "ok"})))
    llm = FakeLLM(script)
    agent = CodeAgent(llm, Workspace(tmp_path, spec={}), compact_threshold_chars=20_000, keep_recent_messages=4)
    result = agent.run()
    assert result.success
    last = llm.requests[-1]
    args0 = json.loads(last[2]["tool_calls"][0]["function"]["arguments"])
    assert ELIDED in args0["content"] and args0["path"] == "f0.txt"
    assert [m.get("reasoning_content") for m in last if m["role"] == "assistant"][:8] == [f"r{i}" for i in range(8)]
    assert (tmp_path / "f0.txt").read_text() == big  # disk untouched


def test_run_pipeline_end_to_end(tmp_path, sample_inputs):
    out = tmp_path / "out"
    llm = FakeLLM(covered_script())
    s = Settings(api_key="unused", input_files=[str(p) for p in sample_inputs], output_dir=str(out))
    result = run_pipeline(s, llm=llm)
    assert result.success
    spec = json.loads((out / ".codeagent/spec.json").read_text())
    assert spec["meta"]["diagram_count"] == 13
    task = llm.requests[0][1]["content"]
    assert "ASR-2" in task and "sql/game_ddl.sql" in task and '"classes"' in task


def test_finish_rejected_for_spec_coverage_gaps(tmp_path, sample_inputs):
    """A project that parses fine but ignores the spec must be sent back with the coverage gaps."""
    from codeagent.preprocess import build_spec, compact_spec
    spec = compact_spec(build_spec(sample_inputs))
    script = [reply(*write_all()), reply(tool_call("finish", {"summary": "done"}, call_id="f1"))]
    llm = FakeLLM(script)
    result = CodeAgent(llm, Workspace(tmp_path, spec=spec), max_idle_nudges=0).run()
    assert not result.success
    rejection = llm.requests[2][-1]["content"]
    assert "finish` rejected" in rejection
    assert "SPEC COVERAGE: classes 0/4" in rejection
    assert "spec class 'Question' is not defined" in rejection
    assert "Spec coverage checklist" in llm.requests[0][1]["content"]
