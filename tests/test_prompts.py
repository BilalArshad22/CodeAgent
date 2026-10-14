from pathlib import Path
from codeagent.preprocess import build_spec, compact_spec
from codeagent import prompts


def test_detect_app_type_sample_is_desktop():
    sample_dir = Path(__file__).resolve().parents[1] / "src" / "codeagent" / "samples"
    spec = compact_spec(build_spec([sample_dir / "Architecture_Documentation.md", sample_dir / "Architecture_View.md"]))
    assert prompts.detect_app_type(spec) == "desktop"
    task_msg = prompts.initial_task(spec)
    assert "Target platform: Standalone Desktop Application with Electron.js (.exe)" in task_msg
    assert "SpaceFractions.exe" in task_msg
    assert "Electron.js" in task_msg


def test_detect_app_type_desktop():
    spec = {
        "summary": {
            "recommended_stack": ["Electron.js", "electron-builder"],
            "deployment_nodes": ["Windows Desktop Client"],
        },
        "documents": [
            {
                "structure": {
                    "heading": "Executive Summary",
                    "paragraphs": ["This is a standalone desktop application packaged as an exe."],
                    "bullets": [],
                    "tables": [],
                    "subsections": [],
                }
            }
        ],
    }
    assert prompts.detect_app_type(spec) == "desktop"
    task_msg = prompts.initial_task(spec)
    assert "Target platform: Standalone Desktop Application with Electron.js (.exe)" in task_msg
    assert "SpaceFractions.exe" in task_msg
    assert "Electron.js" in task_msg


def test_detect_app_type_empty_is_desktop():
    assert prompts.detect_app_type({}) == "desktop"
    assert prompts.detect_app_type(None) == "desktop"
    task_msg = prompts.initial_task({})
    assert "Target platform" in task_msg
