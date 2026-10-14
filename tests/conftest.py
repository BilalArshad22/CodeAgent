import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from codeagent.llm import LLMResponse  # noqa: E402

SAMPLES = ROOT / "src" / "codeagent" / "samples"


@pytest.fixture
def sample_inputs():
    return [SAMPLES / "Architecture_Documentation.md", SAMPLES / "Architecture_View.md"]


def tool_call(name, args, call_id=None):
    return {"id": call_id or f"call_{name}_{abs(hash(json.dumps(args, sort_keys=True))) % 10**8}",
            "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


def reply(*calls, content="", reasoning=None, finish_reason="tool_calls"):
    msg = {"role": "assistant", "content": content}
    if reasoning:
        msg["reasoning_content"] = reasoning
    if calls:
        msg["tool_calls"] = list(calls)
    return LLMResponse(message=msg, finish_reason=finish_reason,
                       usage={"prompt_tokens": 100, "completion_tokens": 50, "prompt_cache_hit_tokens": 10})


class FakeLLM:
    """Replays scripted responses and records every request it receives."""

    def __init__(self, script):
        self.script = list(script)
        self.requests = []

    def chat(self, messages, tools=None):
        self.requests.append(json.loads(json.dumps(messages)))
        if not self.script:
            return reply(content="(script exhausted)", finish_reason="stop")
        step = self.script.pop(0)
        return step(messages) if callable(step) else step


MINIMAL_PROJECT = {
    "README.md": "# Demo\n\nRun `npm test`.\n",
    "package.json": json.dumps({"name": "demo", "main": "src/index.js", "scripts": {"test": "node --test"}}),
    "src/index.js": "const { add } = require('./math');\nmodule.exports = { add };\n",
    "src/math.js": "function add(a, b) {\n  return a + b;\n}\nmodule.exports = { add };\n",
    "tests/math.test.js": "const test = require('node:test');\nconst assert = require('assert');\n"
                          "const { add } = require('../src/math');\ntest('add', () => assert.strictEqual(add(1, 2), 3));\n",
    "Dockerfile": "FROM node:18-alpine\nWORKDIR /app\nCOPY . .\nCMD [\"node\", \"src/index.js\"]\n",
}


# A small but genuine implementation of the sample "Space Fractions" spec. It must pass
# spec coverage; anything thinner (e.g. the Gemini flash-lite output) must not.
SPACE_FRACTIONS_PROJECT = {
    **MINIMAL_PROJECT,
    "package.json": json.dumps({"name": "space-fractions", "main": "src/app.js",
                                "scripts": {"test": "node --test"}}),
    "src/index.js": "module.exports = require('./app');\n",
    "src/domain/question.js": """class Question {
  constructor(id, prompt, options, answer) {
    this.id = id; this.prompt = prompt; this.options = options; this.answer = answer;
  }
  getPrompt() { return this.prompt; }
  getOptions() { return [...this.options]; }
  checkAnswer(choice) { return choice === this.answer; }
}
module.exports = { Question };
""",
    "src/domain/game.js": """const STATES = { Playing: 'Playing', Paused: 'Paused', GameOver: 'GameOver' };
class Game {
  constructor(id, questions) { this.id = id; this.questions = questions; this.score = 0; this.index = 0; this.state = null; }
  play() { this.state = STATES.Playing; return this.current().getPrompt(); }
  current() { return this.questions[this.index]; }
  submitAnswer(choice) {
    if (this.state !== STATES.Playing) throw new Error('not playing');
    const correct = this.current().checkAnswer(choice);
    if (correct) this.score += 1;
    this.index += 1;
    if (this.index >= this.questions.length) this.gameOver();
    return correct;
  }
  pause() { if (this.state !== STATES.Playing) throw new Error('invalid'); this.state = STATES.Paused; }
  resume() { if (this.state !== STATES.Paused) throw new Error('invalid'); this.state = STATES.Playing; }
  gameOver() { if (this.state !== STATES.Playing) throw new Error('invalid'); this.state = STATES.GameOver; }
  viewScore() { return this.score; }
}
module.exports = { Game, STATES };
""",
    "src/domain/user.js": """class User {
  constructor(id, username) { this.id = id; this.username = username; }
  playGame(game) { return game.play(); }
  viewScore(game) { return game.viewScore(); }
}
module.exports = { User };
""",
    "src/domain/admin.js": """class Admin {
  constructor(id, username, bank) { this.id = id; this.username = username; this.bank = bank; }
  updateQuestions(questions) { this.bank.splice(0, this.bank.length, ...questions); return true; }
}
module.exports = { Admin };
""",
    "src/app.js": """const express = require('express');
const app = express();
app.get('/play', (req, res) => res.json({}));
app.get('/score', (req, res) => res.json({}));
app.put('/questions', (req, res) => res.json({}));
app.get('/help', (req, res) => res.json({}));
module.exports = app;
""",
    "tests/game.test.js": """const test = require('node:test');
const assert = require('assert');
const { Game } = require('../src/domain/game');
const { Question } = require('../src/domain/question');
const q = () => [new Question('1', '1/2 + 1/4?', ['3/4', '1/2'], '3/4')];
test('play starts in Playing', () => { const g = new Game('g', q()); g.play(); assert.equal(g.state, 'Playing'); });
test('pause moves to Paused', () => { const g = new Game('g', q()); g.play(); g.pause(); assert.equal(g.state, 'Paused'); });
test('resume returns to Playing', () => { const g = new Game('g', q()); g.play(); g.pause(); g.resume(); assert.equal(g.state, 'Playing'); });
test('gameOver ends the game', () => { const g = new Game('g', q()); g.play(); g.gameOver(); assert.equal(g.state, 'GameOver'); });
test('submitAnswer scores and view score', () => { const g = new Game('g', q()); g.play(); g.submitAnswer('3/4'); assert.equal(g.viewScore(), 1); });
test('GET /play and /score routes exist', () => { assert.ok('/play' && '/score'); });
test('PUT /questions updates questions', () => { assert.ok('/questions'); });
test('GET /help returns help', () => { assert.ok('/help'); });
""",
}


def covered_script():
    """Agent script that writes SPACE_FRACTIONS_PROJECT and finishes."""
    return [
        reply(tool_call("todo_write", {"todos": [{"content": "build", "status": "in_progress"}]}),
              reasoning="Plan first."),
        reply(*[tool_call("write_file", {"path": p, "content": c}) for p, c in SPACE_FRACTIONS_PROJECT.items()]),
        reply(tool_call("check_project", {})),
        reply(tool_call("finish", {"summary": "Built Space Fractions."})),
    ]
