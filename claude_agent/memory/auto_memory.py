from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from threading import Thread
from typing import Any

from claude_agent.multi_agent.sub_agent import SubAgent


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _messages_to_text(messages: list[dict[str, str]]) -> str:
    return "\n".join(f"{m.get('role','')}: {m.get('content','')}".strip() for m in messages)


def _extract_yaml_front_matter(content: str) -> str:
    """从md文件中提取YAML frontmatter元数据"""
    lines = content.split("\n")
    if not lines or lines[0].strip() != "---":
        return ""

    yaml_lines = []
    i = 1
    while i < len(lines) and lines[i].strip() != "---":
        yaml_lines.append(lines[i])
        i += 1

    if i >= len(lines):
        return ""

    return " | ".join(yaml_lines)


def _safe_read_text(path: Path, max_chars: int = 80_000) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 20] + "\n...[snip]"


def _list_memory_files(memory_dir: Path) -> list[Path]:
    '''列出记忆文件'''
    if not memory_dir.exists():
        return [] # 按文件名排序（因为文件名包含时间戳，所以按时间排序）
    return sorted([p for p in memory_dir.glob("*.md") if p.is_file()], key=lambda p: p.name)


@dataclass(slots=True)
class CursorState:
    cursor: int # 已处理到的消息索引
    epoch: int # 纪元号（每次手动重置记忆时递增）


def _read_cursor_state(path: Path) -> CursorState: # 维护 cursor.json （持久化游标与 epoch）
    '''从JSON文件读取游标状态，返回CursorState对象'''
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        cursor = int(data.get("cursor", 0))
        epoch = int(data.get("epoch", 0))
        return CursorState(cursor=max(0, cursor), epoch=max(0, epoch))
    except Exception:
        return CursorState(cursor=0, epoch=0)


def _write_cursor_state(path: Path, state: CursorState) -> None:
    '''将游标状态写入JSON文件'''
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"cursor": state.cursor, "epoch": state.epoch}, ensure_ascii=False), encoding="utf-8")


@dataclass(slots=True)
class PendingTask:
    session_id: str # 会话ID
    messages: list[dict[str, str]] # 完整的消息列表
    start_cursor: int # 起始位置
    end_cursor: int # 结束位置
    epoch: int # 处理时的epoch
    created_at: str # ISO格式的创建时间


@dataclass(slots=True)
class _Runner:
    lock: Lock # 保护共享状态
    running: bool # 后台线程是否在运行
    thread: Thread | None # 后台线程对象
    pending: PendingTask | None # 待处理的任务
    inflight_end_cursor: int # 正在处理的任务的结束游标，新任务会从max(cursor_state.cursor, runner.inflight_end_cursor)开始


_RUNNERS: dict[str, _Runner] = {} # 全局运行器字典：使用字典存储后台线程，用户之间不互相阻塞


def _runner_for(user_id: str) -> _Runner:
    '''获取或创建用户的运行器'''
    r = _RUNNERS.get(user_id)
    if r is None:
        r = _Runner(lock=Lock(), running=False, thread=None, pending=None, inflight_end_cursor=0)
        _RUNNERS[user_id] = r
    return r


@dataclass(slots=True)
class AutoMemory:
    storage_root: Path # 记忆存储根目录
    user_id: str # 用户标识，用于隔离不同用户的记忆
    every_n_rounds: int = 8 # 每隔多少轮对话触发一次记忆写入
    _rounds_since_last: int = 0 # 距离上次写入已经过的轮次数

    def memory_dir(self) -> Path:
        return self.storage_root / self.user_id / "auto_memory"

    def cursor_file(self) -> Path:
        return self.memory_dir() / "cursor.json"

    def should_write(self) -> bool:
        return self._rounds_since_last >= self.every_n_rounds

    def on_round_completed(self) -> None:
        self._rounds_since_last += 1

    def bump_epoch_and_reset_cursor(self, message_count: int) -> None:
        '''在content_manager中，每次压缩完上下文后，调用以重置游标（messages已改变）'''
        state = _read_cursor_state(self.cursor_file()) # 读取当前状态
        # 创建新状态：cursor设置为当前消息数，epoch加1（下次处理会从最新消息开始，旧记忆不会重复处理）
        _write_cursor_state(self.cursor_file(), CursorState(cursor=max(0, int(message_count)), epoch=state.epoch + 1))

    def schedule_write(self, messages: list[dict[str, str]], *, session_id: str, force: bool = False) -> None:
        if not force and not self.should_write():
            return

        cursor_state = _read_cursor_state(self.cursor_file()) # 读取当前游标状态
        runner = _runner_for(self.user_id) # 获取用户的运行器
        with runner.lock: # 获取线程锁，确保同一时刻只有一个线程执行块内代码
            start_cursor = max(cursor_state.cursor, runner.inflight_end_cursor) # 起始游标取两者最大值
            end_cursor = len(messages) # 结束游标是当前总消息数
            if end_cursor <= start_cursor:
                if not force:
                    self._rounds_since_last = 0
                return

            runner.pending = PendingTask(
                session_id=session_id,
                messages=list(messages), # 创建副本，防止外部修改
                start_cursor=start_cursor,
                end_cursor=end_cursor,
                epoch=cursor_state.epoch,
                created_at=_utc_now_iso(),
            )
            self._rounds_since_last = 0 # 重置轮数计数器（已调度任务）
            if runner.running: # 如果后台线程已在运行，直接返回（任务已存入pending）
                return
            runner.running = True # 标记为运行中
            runner.thread = Thread(target=self._run_background, daemon=True) # 创建后台线程
            runner.thread.start()

    def _run_background(self) -> None:
        runner = _runner_for(self.user_id) # 获取当前用户的运行器
        try:
            while True:
                with runner.lock:
                    task = runner.pending # 加锁取出待处理任务
                    runner.pending = None # 清空pending槽位
                    if task is not None:
                        runner.inflight_end_cursor = max(runner.inflight_end_cursor, task.end_cursor) # 更新正在处理的最大游标位置
                if task is None: # 没有任务就退出线程
                    return
                self._write_memory(task) # 执行实际的记忆写入（耗时操作）
        finally:
            with runner.lock:
                runner.running = False
                runner.inflight_end_cursor = 0

    def _write_memory(self, task: PendingTask) -> None:
        _ensure_dir(self.memory_dir())
        memory_files = _list_memory_files(self.memory_dir())
        memory_texts: list[str] = [] # 1. 读取所有现有的记忆文件，排除memory.md和session.md两个特殊文件
        for p in memory_files:
            if p.name.lower() == "memory.md":
                continue
            if p.name.lower() == "session.md":
                continue
            memory_texts.append(_extract_yaml_front_matter(_safe_read_text(p)))
        all_memory = "\n".join(memory_texts).strip()

        delta_messages = task.messages[task.start_cursor : task.end_cursor]
        delta_text = _messages_to_text(delta_messages)

        name = datetime.now(timezone.utc).strftime("memory_%Y%m%d_%H%M%S")

        round2_prompt = "\n".join( # 2. 后台子Agent生成摘要
            [
                "You are a long-term memory writer.",
                "Write a markdown file with YAML front matter then body.",
                "YAML must contain: name, description. The structure of YAML is:",
                "---",
                "name: {the memory name}",
                "description: {a concise description of body}",
                "---",
                "",
                "Body is written according to 'Context', and shouldn't repeat with 'History Memory'.",
                "Body should be the long-term memory content, and points below worth recording:",
                "## 1. User: The information of user, such as his profession, project experience and so on. It's not a profile of the user, but to help the user work well.",
                "## 2. Feedback: User have must said something and denied something. When record a feedback, it required two things:",
                "    Required 1: Each record must contain tree points: ①what's the detailed rule;②What's the source of the rule;③What's the using scene of the rule."
                "    Required 2: You should focus on both the user correct and the user deny."
                "## 3. Project: The information of the project, who's the worker, do what, and what's the date?(The relative date should transform to absolute date)",
                "## 4. Reference: The indices of outer source files, such as the root of dashboard, debug log...",
                "Things below don't worth record:",
                "## 1. The negative comment of user and the user information irrelevant to works, for the aims of record is to help the user works better."
                "## 2. The structure/mode/path of codes/project, for these things can be interfered from codes."
                "## 3. What's doing now, for the record is about long-term memory but not short-term details."
                "",
                "Context",
                delta_text,
                "",
                "History Memory",
                all_memory,
                "",
                "If no things worth record, return nothing. Return ONLY the markdown content.",
            ]
        )
        agent = SubAgent()
        body = agent.run(round2_prompt).strip()

        out_path = self.memory_dir() / f"{name}.md"
        out_path.write_text(body + "\n", encoding="utf-8")

        current_state = _read_cursor_state(self.cursor_file())
        if current_state.epoch == task.epoch:
            _write_cursor_state(self.cursor_file(), CursorState(cursor=task.end_cursor, epoch=current_state.epoch))

    def debug_state(self) -> dict[str, Any]:
        state = _read_cursor_state(self.cursor_file())
        runner = _runner_for(self.user_id)
        with runner.lock:
            running = runner.running
            has_pending = runner.pending is not None
        return {
            "user_id": self.user_id,
            "every_n_rounds": self.every_n_rounds,
            "rounds_since_last": self._rounds_since_last,
            "running": running,
            "has_pending": has_pending,
            "cursor": state.cursor,
            "epoch": state.epoch,
            "memory_dir": str(self.memory_dir()),
        }
