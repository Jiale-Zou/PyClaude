from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

from claude_agent.security.path_validator import PathValidator


class SemanticDecisionType(str, Enum):
    ALLOW = "allow"
    CONFIRM = "confirm"


@dataclass(frozen=True, slots=True)
class SemanticDecision:
    decision: SemanticDecisionType
    normalized: str
    reason: str
    matches: list[dict[str, Any]]


@dataclass(slots=True)
class SemanticAnalyzer:
    dangerous_patterns: list[dict[str, str]] = None  # type: ignore[assignment]
    risk_keywords: set[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.dangerous_patterns is None:
            self.dangerous_patterns = [
                {"pattern": r"rm\s+-rf?\s*[/~]", "description": "递归删除根目录/家目录，极高危"},
                {"pattern": r"chmod\s+777\b", "description": "赋予文件全部权限，高危"},
                {"pattern": r"\bdd\b\s+if=", "description": "磁盘写入/覆盖（dd if=），极高危"},
                {"pattern": r"\bmkfs\.", "description": "格式化文件系统（mkfs.*），极高危"},
                {"pattern": r"\bshutdown\b|\breboot\b", "description": "关机/重启操作，高危"},
                {"pattern": r"\bpkill\b|\bkillall\b", "description": "批量杀进程，高危"},
                {"pattern": r"\binit\s+0\b", "description": "关机（init 0），高危"},
                {"pattern": r"\bpoweroff\b", "description": "关机（poweroff），高危"},
                {"pattern": r"\bdel\b\s+.*\s+/s\b", "description": "Windows 递归删除（del /s），高危"},
                {"pattern": r"\brd\b\s+/s\b|\brmdir\b\s+/s\b", "description": "Windows 递归删除目录（rd/rmdir /s），高危"},
                {"pattern": r"\bformat\b\s+[a-z]:", "description": "Windows 格式化盘符（format X:），极高危"},
                {"pattern": r"Remove-Item\b.*-Recurse\b.*-Force\b", "description": "PowerShell 强制递归删除，高危"},
            ]
        if self.risk_keywords is None:
            self.risk_keywords = {
                "delete",
                "format",
                "override",
                "flush",
                "drop",
                "truncate",
                "reboot",
                "shutdown",
                "init 0",
                "pkill",
            }

    def _normalize(self, command: str) -> str:
        return " ".join(command.strip().split())

    def analyze(self, command: str) -> list[dict[str, Any]]:
        normalized = self._normalize(command)
        if not normalized:
            return [{"type": "empty", "description": "空命令"}]

        hits: list[dict[str, Any]] = []
        for item in self.dangerous_patterns:
            pattern = item.get("pattern", "")
            description = item.get("description", "")
            if not pattern:
                continue
            if re.search(pattern, normalized, flags=re.IGNORECASE):
                hits.append({"type": "pattern", "pattern": pattern, "description": description})

        lowered = normalized.lower()
        for kw in self.risk_keywords:
            kw_l = kw.lower()
            if " " in kw_l:
                if kw_l in lowered:
                    hits.append({"type": "keyword", "keyword": kw, "description": f"命中高风险关键词: {kw}"})
                continue
            if re.search(rf"\b{re.escape(kw_l)}\b", lowered):
                hits.append({"type": "keyword", "keyword": kw, "description": f"命中高风险关键词: {kw}"})

        return hits

    def classify(self, command: str) -> SemanticDecision:
        normalized = self._normalize(command)
        hits = self.analyze(command)
        if hits:
            reason = hits[0].get("description", "命中高风险规则，需要人为确认")
            return SemanticDecision(
                decision=SemanticDecisionType.CONFIRM,
                normalized=normalized,
                reason=str(reason),
                matches=hits,
            )
        return SemanticDecision(
            decision=SemanticDecisionType.ALLOW,
            normalized=normalized,
            reason="No dangerous semantic patterns detected.",
            matches=[],
        )

    def is_safe(self, command: str) -> bool:
        return self.classify(command).decision == SemanticDecisionType.ALLOW

    def requires_confirmation(self, command: str) -> bool:
        return self.classify(command).decision == SemanticDecisionType.CONFIRM

    def decision_for_frontend(self, command: str) -> dict[str, str]:
        decision = self.classify(command)
        return {"decision": decision.decision.value, "normalized": decision.normalized, "reason": decision.reason}

    def check_path(self, path: str) -> dict[str, str]:
        return PathValidator().decision_for_frontend(path)
