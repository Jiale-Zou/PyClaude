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
    qwen_key: str = ""
    deepseek_key: str = ""
    glm_key: str = ""
    kimi_key: str = ""
