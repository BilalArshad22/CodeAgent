"""Persistent user settings (API key, model, last used paths)."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-v4-pro"
KNOWN_MODELS = ["deepseek-v4-pro", "deepseek-flash"]

# DeepSeek is the required provider. Gemini (via its OpenAI-compatible endpoint)
# is only a convenience for cheap testing during development.
PROVIDERS = {
    "deepseek": {
        "label": "DeepSeek (official)",
        "base_url": DEFAULT_BASE_URL,
        "models": KNOWN_MODELS,
        "env": "DEEPSEEK_API_KEY",
    },
    "gemini": {
        "label": "Gemini (testing only)",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "models": ["gemini-3.1-flash-lite", "gemini-3.5-flash", "gemini-3.8-flash", "gemini-3.1-pro"],
        "env": "GEMINI_API_KEY",
    },
}


def config_dir() -> Path:
    """%APPDATA%\\CodeAgent on Windows, ~/.config/CodeAgent elsewhere."""
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA") or Path.home())
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "CodeAgent"


def config_path() -> Path:
    return config_dir() / "settings.json"


@dataclass
class Settings:
    provider: str = "deepseek"
    api_key: str = ""
    gemini_api_key: str = ""
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    thinking: bool = True
    max_turns: int = 120
    max_tokens: int = 32000
    remember_key: bool = True
    input_files: list[str] = field(default_factory=list)
    output_dir: str = ""

    def effective_api_key(self) -> str:
        if self.provider == "gemini":
            return (self.gemini_api_key.strip() or os.environ.get("GEMINI_API_KEY", "").strip()
                    or os.environ.get("GOOGLE_API_KEY", "").strip())
        return self.api_key.strip() or os.environ.get("DEEPSEEK_API_KEY", "").strip()


def load_settings(path: Path | None = None) -> Settings:
    path = path or config_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Settings()
    known = {f.name for f in fields(Settings)}
    try:
        return Settings(**{k: v for k, v in raw.items() if k in known})
    except TypeError:
        return Settings()


def save_settings(settings: Settings, path: Path | None = None) -> Path:
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = asdict(settings)
    if not settings.remember_key:
        data["api_key"] = ""
        data["gemini_api_key"] = ""
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path
