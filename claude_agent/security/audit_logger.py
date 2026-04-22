from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class AuditLogger:
    storage_root: Path = Path.cwd() / "storage"

    def _as_command_str(self, command: Any) -> str:
        if command is None:
            return ""
        if isinstance(command, dict):
            value = command.get("normalized") or command.get("command") or command.get("path") or ""
            return str(value)
        value = getattr(command, "normalized", None)
        if value is not None:
            return str(value)
        return str(command)

    def _as_reason_str(self, reason: Any, fallback: Any = None) -> str:
        if isinstance(reason, dict):
            value = reason.get("reason") or ""
            return str(value)
        if reason is None:
            value = getattr(fallback, "reason", None)
            return "" if value is None else str(value)
        return str(reason)

    def _log_file(self, user_id: str) -> Path:
        return self.storage_root / user_id / "logs" / "security_log.txt"

    def log_rejection(self, user_id: str, command: Any, reason: Any = None) -> None:
        '''专门记录被拒绝/需确认的安全事件'''
        file_path = self._log_file(user_id)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        cmd_s = self._as_command_str(command)
        reason_s = self._as_reason_str(reason, fallback=command)
        line = f"command: {cmd_s} | reason: {reason_s}\n"
        with file_path.open("a", encoding="utf-8") as f:
            f.write(line)

    def log(self, user_id: str, event: str) -> None:
        '''通用日志记录器'''
        file_path = self._log_file(user_id)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with file_path.open("a", encoding="utf-8") as f:
            f.write(event.rstrip("\n") + "\n")
