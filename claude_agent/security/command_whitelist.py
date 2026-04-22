from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal


class CommandDecisionType(str, Enum):
    ALLOW = "allow"
    CONFIRM = "confirm"


@dataclass(frozen=True, slots=True)
class CommandDecision:
    decision: CommandDecisionType
    normalized: str
    reason: str


@dataclass(slots=True)
class CommandWhitelist:
    auto_allow_commands: set[str] = field(
        default_factory=lambda: {
            "cat",
            "head",
            "tail",
            "less",
            "more",
            "wc",
            "grep",
            "rg",
            "ag",
            "find",
            "ls",
            "pwd",
            "whoami",
            "uname",
            "date",
            "dir",
            "type",
        }
    ) #  安全的基础命令
    auto_allow_git_subcommands: set[str] = field(default_factory=lambda: {"status", "log", "diff", "show"}) # 只读的git子命令
    auto_allow_exact: set[str] = field(default_factory=set) # 完全匹配的命令（优先级最高）

    def classify(self, command: str) -> CommandDecision:
        normalized = " ".join(command.strip().split())
        if not normalized:
            return CommandDecision(
                decision=CommandDecisionType.CONFIRM,
                normalized="",
                reason="Empty command requires confirmation.",
            )

        if normalized in self.auto_allow_exact:
            return CommandDecision(decision=CommandDecisionType.ALLOW, normalized=normalized, reason="Exact allowlist.")

        parts = normalized.split(" ")
        exe = parts[0].lower()
        args = parts[1:]

        if exe == "git":
            sub = (args[0].lower() if args else "")
            if sub in self.auto_allow_git_subcommands:
                return CommandDecision(
                    decision=CommandDecisionType.ALLOW,
                    normalized=normalized,
                    reason=f"Readonly git subcommand: {sub}.",
                )
            return CommandDecision(
                decision=CommandDecisionType.CONFIRM,
                normalized=normalized,
                reason=f"Non-readonly git subcommand: {sub or '(none)'} requires confirmation.",
            )

        if exe in self.auto_allow_commands:
            return CommandDecision(
                decision=CommandDecisionType.ALLOW,
                normalized=normalized,
                reason=f"Readonly command: {exe}.",
            )

        return CommandDecision(
            decision=CommandDecisionType.CONFIRM,
            normalized=normalized,
            reason="Command is not in readonly allowlist; requires confirmation.",
        )

    def is_allowed(self, command: str) -> bool:
        return self.classify(command).decision == CommandDecisionType.ALLOW

    def requires_confirmation(self, command: str) -> bool:
        return self.classify(command).decision == CommandDecisionType.CONFIRM

    def decision_for_frontend(self, command: str) -> dict[str, str]:
        decision = self.classify(command)
        return {"decision": decision.decision.value, "normalized": decision.normalized, "reason": decision.reason}


