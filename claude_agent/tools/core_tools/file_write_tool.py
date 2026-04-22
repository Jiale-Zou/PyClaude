from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from claude_agent.tools.base_tool import BaseTool
from claude_agent.security.path_validator import PathDecisionType, PathValidator


class FileWriteInput(BaseModel):
    file_path: str # 要写入的文件路径
    content: str # 要写入的文本内容
    encoding: str = "utf-8"
    confirmed: bool = False


class FileWriteOutput(BaseModel):
    path: str # 回显写入的绝对路径
    bytes_written: int # 实际写入的字节数


@dataclass(slots=True)
class FileWriteTool(BaseTool):
    name: str = "file_write"
    search_hint: str = "创建或覆盖写入文件内容，适合生成配置与保存结果到磁盘"
    description: str = "Write a file to disk. Accept absolute path/environment variable path."
    input_schema = FileWriteInput
    output_schema = FileWriteOutput
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
                    {"decision": "confirm", "normalized": decision.normalized, "reason": "File write requires confirmation."},
                    ensure_ascii=False,
                )
            )

    def execute(self, **kwargs: Any) -> BaseModel:
        decision = PathValidator().classify(str(kwargs["file_path"]))
        path = Path(decision.normalized)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = str(kwargs["content"]).encode(str(kwargs.get("encoding", "utf-8")), errors="replace")
        path.write_bytes(data)
        return FileWriteOutput(path=str(path), bytes_written=len(data))
