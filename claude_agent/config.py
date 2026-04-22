from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class AgentConfig:
    token_budget: int = 16000
    model_name: str = "qwen-plus"
    temperature: float = 0.2
    project_root: Path = Path.cwd()
    storage_dir: Path = Path(__file__).parent.parent / "storage"
    qwen_key: str = "sk-a6647968836d4d9587d9adb77e659727"
    deepseek_key: str = "sk-0c2d99c2e46b41f4936baf72a955e032"
    glm_key: str = "dd1b4f5dcd6347689195e080ac607291.9KLsNzudydW8lNFh"
    kimi_key: str = "sk-Hh4kTUFbLI1YHz7nUyQ7Zm6dF0B50IeJf8prnkexVPkqw7Un"
