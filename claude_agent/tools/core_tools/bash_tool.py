from __future__ import annotations

import json
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from claude_agent.tools.base_tool import BaseTool
from claude_agent.security import SemanticAnalyzer
from claude_agent.security.command_whitelist import CommandWhitelist
from claude_agent.security.path_validator import PathDecisionType, PathValidator


class BashInput(BaseModel):
    command: str # 要执行的命令
    cwd: str | None = None # 命令执行的工作目录
    timeout_sec: int = 30 # 超时时间，防止命令无限运行
    confirmed: bool = False


class BashOutput(BaseModel):
    stdout: str # 标准输出内容
    stderr: str # 标准错误内容
    exit_code: int # 命令退出码（0 表示成功，非0 表示失败）


@dataclass(slots=True)
class BashTool(BaseTool):
    name: str = "bash"
    search_hint: str = "运行系统命令并返回stdout/stderr，适合诊断与执行任务"
    description: str = "Execute a shell command, used only when other tools are disabled."
    input_schema = BashInput
    output_schema = BashOutput
    needs_permission: bool = True

    def _extract_candidate_paths(self, command: str) -> list[str]:
        try:
            parts = shlex.split(command, posix=False) # 尝试用 shlex 智能分割命令（能正确处理引号内的空格）
        except Exception:
            parts = command.split() # 解析失败时回退到简单空格分割

        candidates: list[str] = []
        for token in parts:
            t = token.strip("\"' ") # 去除首尾引号
            if not t:
                continue
            if t.startswith(("-", "/")): # 跳过命令行选项（以 - 或 / 开头）和绝对路径
                continue
            if "\\" in t or "/" in t or t.startswith(".") or (len(t) >= 3 and t[1:3] == ":\\" or t[1:3] == ":/"): # 检测可能是路径的标记：包含路径分隔符，或符合 Windows 盘符格式
                candidates.append(t)
        return candidates

    def validate_permission(self, **kwargs: Any) -> None:
        command = str(kwargs.get("command", "")).strip()
        confirmed = bool(kwargs.get("confirmed", False))
        # ===== 第一重：命令白名单校验 =====
        whitelist_decision = CommandWhitelist().classify(command)
        # ===== 第二重：语义分析校验 =====
        semantic_decision = SemanticAnalyzer().classify(command)
        # ===== 第三重：路径安全校验 =====
        path_validator = PathValidator()
        for token in self._extract_candidate_paths(command):
            path_decision = path_validator.classify(token)
            if path_decision.decision == PathDecisionType.DENY:
                raise PermissionError(
                    json.dumps(
                        {"decision": "deny", "normalized": path_decision.normalized, "reason": path_decision.reason},
                        ensure_ascii=False,
                    )
                )

        if confirmed:
            return

        # 收集所有要求确认的原因
        reasons: list[str] = []
        if whitelist_decision.decision.value == "confirm":
            reasons.append(whitelist_decision.reason)
        if semantic_decision.decision.value == "confirm":
            reasons.append(semantic_decision.reason)
        if not reasons:
            reasons.append("BashTool requires confirmation.")

        raise PermissionError(
            json.dumps(
                {"decision": "confirm", "normalized": " ".join(command.split()), "reason": " | ".join(reasons)},
                ensure_ascii=False,
            )
        )

    def execute(self, **kwargs: Any) -> BaseModel:
        command = str(kwargs["command"])
        timeout_sec = int(kwargs.get("timeout_sec", 30))

        cwd: str | None = kwargs.get("cwd") # ===== 工作目录校验 =====
        if cwd:
            decision = PathValidator().classify(cwd)
            if decision.decision != PathDecisionType.ALLOW:
                raise PermissionError(
                    json.dumps(
                        {"decision": decision.decision.value, "normalized": decision.normalized, "reason": decision.reason},
                        ensure_ascii=False,
                    )
                )
            run_cwd = Path(decision.normalized)
        else:
            run_cwd = None

        completed = subprocess.run( # Window: Powershell;  Linux/macOS 上会是 ["/bin/bash", "-c", command]
            ["powershell", "-NoProfile", "-Command", command],
            cwd=str(run_cwd) if run_cwd is not None else None,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_sec,
        )
        return BashOutput(stdout=completed.stdout, stderr=completed.stderr, exit_code=int(completed.returncode))
