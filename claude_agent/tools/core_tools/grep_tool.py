from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from claude_agent.tools.base_tool import BaseTool


class GrepInput(BaseModel):
    pattern: str # 必需：要搜索的正则表达式模式
    path: str | None = None # 搜索的起始路径，默认为当前目录
    glob: str = "**/*" # 件匹配模式，默认递归搜索所有文件
    encoding: str = "utf-8" # 读取文件时使用的编码
    confirmed: bool = False # 权限确认标记，用于需要用户确认的路径


class GrepOutput(BaseModel):
    matches: list[str] # 所有匹配行的列表，格式为 "文件路径:行号:内容"
    count: int # 匹配的总行数


@dataclass(slots=True)
class GrepTool(BaseTool):
    name: str = "grep"
    search_hint: str = "在目录内用正则搜索文本内容，返回匹配行与行号"
    description: str = "Search file contents with a regular expression."
    input_schema = GrepInput
    output_schema = GrepOutput
    needs_permission: bool = False

    def _run_rg(self, pattern: str, base: Path, glob_pattern: str) -> list[str] | None:
        if shutil.which("rg") is None: # shutil.which("rg") 在系统 PATH 中查找 rg 命令，找不到返回 None
            return None
        try:
            completed = subprocess.run(
                ["rg", "--line-number", "--no-heading", "--color", "never", "--glob", glob_pattern, pattern, str(base)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except Exception:
            return None
        if completed.returncode not in (0, 1): # rg 的返回码：0 表示找到匹配，1 表示未找到，其他表示错误
            return None
        lines = [line for line in completed.stdout.splitlines() if line.strip()]
        return lines

    def execute(self, **kwargs: Any) -> BaseModel:
        pattern_text = str(kwargs["pattern"]) # 1. 提取并规范化输入参数
        base = str(kwargs.get("path") or ".")
        glob_pattern = str(kwargs.get("glob", "**/*"))
        root = Path(base)

        rg_lines = self._run_rg(pattern_text, root, glob_pattern) # 2. 优先尝试使用 ripgrep 执行搜索
        if rg_lines is not None:
            return GrepOutput(matches=rg_lines, count=len(rg_lines))

        pattern = re.compile(pattern_text) # 3. 回退方案：编译正则表达式，re.compile 会验证表达式的有效性
        results: list[str] = []
        for file_path in root.glob(glob_pattern): # 4. 使用 Path.glob 遍历符合模式的文件
            if not file_path.is_file():
                continue
            try:
                text = file_path.read_text(encoding=str(kwargs.get("encoding", "utf-8")), errors="ignore")
            except OSError:
                continue
            for line_no, line in enumerate(text.splitlines(), start=1): # 5. 逐行搜索
                if pattern.search(line):
                    results.append(f"{file_path}:{line_no}:{line}")
        return GrepOutput(matches=results, count=len(results))
