from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from claude_agent.tools.base_tool import BaseTool
from claude_agent.security.path_validator import PathDecisionType, PathValidator


class FileEditInput(BaseModel):
    file_path: str # 要编辑的文件路径
    old: str # 要被替换的旧文本（查找目标）
    new: str # 替换后的新文本
    count: int = 0 # 替换次数限制。0 表示替换所有匹配项
    encoding: str = "utf-8"
    confirmed: bool = False


class FileEditOutput(BaseModel):
    path: str # 回显文件路径
    replacements: int # 实际替换的次数
    changed: bool # 文件是否发生了变更


@dataclass(slots=True)
class FileEditTool(BaseTool):
    name: str = "file_edit"
    search_hint: str = "对文件做精确字符串替换，适合批量改名、更新配置与修复文本"
    description: str = "Edit a file on disk."
    input_schema = FileEditInput
    output_schema = FileEditOutput
    needs_permission: bool = True

    def validate_permission(self, **kwargs: Any) -> None:
        decision = PathValidator().classify(str(kwargs.get("file_path", "")))
        if decision.decision == PathDecisionType.DENY:
            raise PermissionError(
                json.dumps(
                    {"decision": "deny", "normalized": decision.normalized, "reason": decision.reason},
                    ensure_ascii=False,
                )
            )
        if not bool(kwargs.get("confirmed", False)):
            raise PermissionError(
                json.dumps(
                    {"decision": "confirm", "normalized": decision.normalized, "reason": "File edit requires confirmation."},
                    ensure_ascii=False,
                )
            )

    def execute(self, **kwargs: Any) -> BaseModel:
        decision = PathValidator().classify(str(kwargs["file_path"]))
        path = Path(decision.normalized)
        if not path.exists() or not path.is_file():
            return FileEditOutput(path=str(path), replacements=0, changed=False)

        encoding = str(kwargs.get("encoding", "utf-8"))
        old = str(kwargs["old"])
        new = str(kwargs["new"])
        count = int(kwargs.get("count", 0))

        original = path.read_text(encoding=encoding, errors="replace") # 读取原始内容，errors="replace" 确保解码失败时不崩溃
        if count == 0:
            updated = original.replace(old, new)
            replacements = original.count(old)
        else:
            updated = original.replace(old, new, count)
            replacements = min(original.count(old), count)

        if updated == original: # # 如果内容没有变化，不执行写入操作（避免无谓的 I/O 和文件修改时间戳更新）
            return FileEditOutput(path=str(path), replacements=0, changed=False)

        path.write_text(updated, encoding=encoding)
        return FileEditOutput(path=str(path), replacements=replacements, changed=True)
