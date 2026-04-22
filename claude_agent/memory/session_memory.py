from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import Thread
from typing import Any

from claude_agent.multi_agent.sub_agent import SubAgent
from claude_agent.utils.token_counter import estimate_tokens


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _messages_to_text(messages: list[dict[str, str]]) -> str:
    '''将消息列表格式化为可读的对话记录'''
    return "\n".join(f"{m.get('role','')}: {m.get('content','')}".strip() for m in messages)


def _default_session_md() -> str:
    '''默认会话记忆模板'''
    return "\n".join(
        [
            "# Session Memory",
            "",
            "## 任务标题和描述",
            "-",
            "",
            "## 当前状态",
            "-",
            "",
            "## 项目结构",
            "-",
            "",
            "## 遇到的错误和解决方案",
            "-",
            "",
            "## 经验教训",
            "-",
            "",
            "## 工作日志",
            "-",
            "",
        ]
    )


@dataclass(slots=True)
class SessionMemory:
    storage_root: Path # 存储根目录
    user_id: str # 用户标识
    session_id: str # 会话标识（关键区别）
    start_threshold_tokens: int = 10_000 # 开始写入的 Token 阈值
    update_step_tokens: int = 5_000 # 后续更新的 Token 步长
    _last_written_at_tokens: int = 0 # 上次写入时的 Token 数
    _running: bool = False # 后台线程运行标志
    _pending: list[dict[str, str]] | None = None # 待处理消息
    _thread: Thread | None = None # 后台线程引用
    _last_error: str | None = None # 最后一次错误信息

    def session_dir(self) -> Path:
        return self.storage_root / self.user_id / "session_memory" / self.session_id

    def session_file(self) -> Path:
        return self.session_dir() / "SESSION.md"

    def current_tokens(self, messages: list[dict[str, str]]) -> int:
        return estimate_tokens(_messages_to_text(messages))

    def should_write(self, messages: list[dict[str, str]]) -> bool:
        tokens = self.current_tokens(messages)
        if tokens < self.start_threshold_tokens:
            return False
        if self._last_written_at_tokens == 0:
            return True
        return (tokens - self._last_written_at_tokens) >= self.update_step_tokens

    def schedule_write(self, messages: list[dict[str, str]]) -> None:
        if not self.should_write(messages):
            return
        self._pending = list(messages) # 保存消息副本并记录当前 Token 数
        self._last_written_at_tokens = self.current_tokens(messages)
        if self._running:
            return
        self._running = True # 防止多线程并发
        self._thread = Thread(target=self._run_background, daemon=True) # 开启后台线程
        self._thread.start()

    def load_text(self) -> str:
        '''读取已有记忆'''
        try:
            return self.session_file().read_text(encoding="utf-8")
        except FileNotFoundError:
            return ""

    def _run_background(self) -> None:
        '''后台处理线程'''
        try:
            while self._pending is not None:
                pending = self._pending
                self._pending = None
                if pending is None:
                    continue
                self._write_session_md(pending)
        except Exception as e:
            self._last_error = repr(e) # 记录错误，不影响主流程
        finally:
            self._running = False

    def wait_last(self, timeout_sec: float | None = None) -> bool:
        '''允许主线程等待后台写入完成。在会话结束前调用此方法可以确保记忆被完整保存。'''
        thread = self._thread
        if thread is None:
            return True
        thread.join(timeout=timeout_sec)
        return not thread.is_alive()

    def _write_session_md(self, messages: list[dict[str, str]]) -> None:
        _ensure_dir(self.session_dir())
        conversation = _messages_to_text(messages)
        prompt = "\n".join(
            [
                "You are a session memory writer. You should write a summary according to 'Conversation'.",
                "Write a structured markdown with sections:",
                "- 任务标题和描述: needs detailed introduction of the current project, including it's theme, aims, targets and so on.",
                "- 当前状态: the current status of the project, including it's schedules, problem and so on.",
                "- 项目结构: the structure of the projector, including it's structure, scheduled plan, realized details and so on.",
                "- 遇到的错误和解决方案: the problem have encountered and theirs solutions.",
                "- 经验教训: the history experience and lessons when conduct the project.",
                "- 工作日志: the working logs, such as the concise process of working history.",
                f"Timestamp: {_utc_now_iso()}",
                "",
                "Conversation:",
                conversation,
            ]
        )
        agent = SubAgent()
        result = agent.run(prompt)
        existing = self.load_text()
        if existing.strip():
            content = existing.rstrip() + "\n\n" + f"---\n\nUpdated: {_utc_now_iso()}\n\n" + result.strip() + "\n"
        else:
            content = _default_session_md().rstrip() + "\n\n" + f"---\n\nUpdated: {_utc_now_iso()}\n\n" + result.strip() + "\n"
        self.session_file().write_text(content, encoding="utf-8")

    def debug_state(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "session_id": self.session_id,
            "start_threshold_tokens": self.start_threshold_tokens,
            "update_step_tokens": self.update_step_tokens,
            "last_written_at_tokens": self._last_written_at_tokens,
            "running": self._running,
            "has_pending": self._pending is not None,
            "last_error": self._last_error,
            "session_file": str(self.session_file()),
        }
