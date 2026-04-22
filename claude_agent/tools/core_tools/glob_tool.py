from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from claude_agent.tools.base_tool import BaseTool


class GlobInput(BaseModel):
    pattern: str # 必需：glob 匹配模式，例如 "*.py" 或 "**/*.txt"
    path: str | None = None # 可选：搜索的起始路径，默认为当前目录 "."
    confirmed: bool = False # 权限确认标记（虽然此工具 needs_permission=False，但保留了字段以备扩展）


class GlobOutput(BaseModel):
    matches: list[str] # 所有匹配到的文件路径列表（字符串形式）
    count: int # 匹配到的文件总数


@dataclass(slots=True)
class GlobTool(BaseTool):
    name: str = "glob"
    search_hint: str = "按通配符搜索匹配的文件路径列表，适合快速定位文件"
    description: str = "Match file paths using glob patterns."
    input_schema = GlobInput
    output_schema = GlobOutput
    needs_permission: bool = False

    def execute(self, **kwargs: Any) -> BaseModel:
        pattern = str(kwargs["pattern"]) # 1. 提取输入参数
        base = str(kwargs.get("path") or ".")
        root = Path(base) # 2. 将基准路径转换为 Path 对象
        matches = [str(p) for p in root.glob(pattern)] # 3. 执行 glob 匹配（Path.glob() 返回一个生成器，遍历所有匹配的文件和目录）
        return GlobOutput(matches=matches, count=len(matches))
