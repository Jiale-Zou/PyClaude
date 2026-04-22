from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from claude_agent.utils.token_counter import estimate_tokens


@dataclass(slots=True)
class ContextManager:
    # Token 预算配置
    token_budget: int = 16000 # 单次请求的 Token 上限
    message_token_budget: int = 200_000 # 对话历史总 Token 上限
    trigger_ratio: float = 0.9 # 触发压缩的阈值比例
    # 工具结果管理
    tool_result_token_budget: int = 1_000 # 工具结果保留在内存中的 Token 阈值
    tool_result_keep_recent: int = 10 # 强制保留最近 N 个工具结果
    tool_result_ttl_seconds: int = 60 * 60 # 工具结果缓存有效期（1小时）
    # 尾部保留策略
    keep_tail_tokens: int = 20_000 # 压缩时保留最新messages的 Token 数
    # 文件恢复配置
    restored_file_max_files: int = 5 # 最多恢复几个最近读取的文件
    restored_file_max_tokens: int = 5_000 # 单个恢复文件的最大 Token 数
    # 存储路径
    storage_root: Path = Path("storage")

    def within_budget(self, text: str) -> bool:
        '''Token 预算检查'''
        return estimate_tokens(text) <= self.token_budget

    def snip(self, text: str, max_chars: int = 4000) -> str:
        '''文本截断'''
        if len(text) <= max_chars:
            return text
        return text[: max_chars - 10] + "\n...[snip]"

    def total_message_tokens(self, messages: list[dict[str, Any]]) -> int:
        '''计算消息总 Token 数'''
        total = 0
        for m in messages:
            total += estimate_tokens(str(m.get("content", "")))
        return total

    def should_compact(self, messages: list[dict[str, Any]]) -> bool:
        '''判断是否需要压缩'''
        return self.total_message_tokens(messages) >= int(self.message_token_budget * self.trigger_ratio)

    def compact_messages(self, messages: list[dict[str, Any]], *, user_id: str, session_id: str) -> list[dict[str, Any]]:
        '''压缩主方法，每次对话后调用一次'''
        out = self._tool_result_budget(messages, user_id=user_id, session_id=session_id)
        out = self._microcompact(out)
        if self.should_compact(out):
            out = self._auto_compact(out, user_id=user_id, session_id=session_id)
        out = self._blocking_limit(out)
        return out

    def load_tool_result(self, file_path: str) -> str:
        try:
            return Path(file_path).read_text(encoding="utf-8", errors="replace")
        except Exception:
            return ""

    def _is_tool_result(self, message: dict[str, Any]) -> bool:
        role = str(message.get("role", ""))
        if role in {"tool", "function"}:
            return True
        if "tool_result_path" in message:
            return True
        if str(message.get("type", "")) == "tool_result":
            return True
        return False

    def _utc_now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _parse_time(self, value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            return None

    def _tool_result_dir(self, user_id: str, session_id: str) -> Path:
        return self.storage_root / user_id / ".ToolResult" / session_id

    def _tool_result_budget(self, messages: list[dict[str, Any]], *, user_id: str, session_id: str) -> list[dict[str, Any]]:
        '''超过 1000 Token 的工具结果写入磁盘，消息中只保留路径和预览'''
        out: list[dict[str, Any]] = []
        base_dir = self._tool_result_dir(user_id, session_id)
        base_dir.mkdir(parents=True, exist_ok=True)

        for i, m in enumerate(messages):
            msg = dict(m)
            if not self._is_tool_result(msg): # 非工具结果消息，直接保留
                out.append(msg)
                continue
            content = str(msg.get("content", ""))
            tool_name = str(msg.get("name") or msg.get("tool_name") or "tool")
            if tool_name == "file_read":
                file_path = self._extract_file_path_from_file_read_content(content)
                if file_path:
                    msg["file_read_path"] = file_path # 记录读取的文件路径
            if estimate_tokens(content) <= self.tool_result_token_budget: # 小结果直接保留在内存
                out.append(msg)
                continue
            # 大结果写入磁盘
            ts = self._utc_now().strftime("%Y%m%d_%H%M%S")
            result_name = f"{tool_name}_{ts}_{i}"
            file_path = base_dir / f"{result_name}.txt"
            file_path.write_text(content, encoding="utf-8")
            # 替换消息内容为磁盘引用 + 预览
            preview = content[:2000]
            msg["tool_result_path"] = str(file_path)
            msg["content"] = "\n".join(
                [
                    "[Tool result stored on disk]",
                    f"path: {file_path}",
                    "",
                    "preview:",
                    preview,
                ]
            )
            out.append(msg)
        return out

    def _microcompact(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        '''清理旧的工具结果，只保留最近 N 个工具结果和 1 小时内的工具结果'''
        tool_indices: list[int] = [i for i, m in enumerate(messages) if self._is_tool_result(m)]
        if not tool_indices:
            return messages

        keep_set = set(tool_indices[-self.tool_result_keep_recent :]) # 强制保留最近 N 个工具结果
        now = self._utc_now()
        out: list[dict[str, Any]] = []
        for i, m in enumerate(messages):
            msg = dict(m)
            if not self._is_tool_result(msg): # 非工具
                out.append(msg)
                continue
            if i in keep_set: # 在保留列表中的，原样保留
                out.append(msg)
                continue

            created_at = self._parse_time(str(msg.get("created_at", ""))) # 检查是否过期
            too_old = True
            if created_at is not None:
                too_old = (now - created_at).total_seconds() >= self.tool_result_ttl_seconds
            if too_old or i not in keep_set: # 既不在保留列表又过期的，清空内容
                msg["content"] = "['Old tool result content cleared']"
            out.append(msg)
        return out

    def _load_session_summary(self, user_id: str, session_id: str) -> str:
        '''加载session memory'''
        p = self.storage_root / user_id / "session_memory" / session_id / "SESSION.md"
        try:
            return p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return ""

    def _take_tail_by_token_budget(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        '''截取最新的messages'''
        acc = 0
        selected: list[dict[str, Any]] = []
        for m in reversed(messages):
            t = estimate_tokens(str(m.get("content", "")))
            if acc + t > self.keep_tail_tokens:
                break
            selected.append(m)
            acc += t
        return list(reversed(selected))

    def _extract_file_path_from_file_read_content(self, content: str) -> str | None:
        '''从 file_read 工具返回的 JSON 结果中提取文件路径'''
        try:
            data = json.loads(content)
        except Exception:
            return None
        if not isinstance(data, dict):
            return None
        value = data.get("path")
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    def _extract_recent_file_reads(self, messages: list[dict[str, Any]]) -> list[str]:
        '''提取最近读取的文件'''
        paths: list[str] = []
        for m in reversed(messages): # 从最新消息往前遍历
            if len(paths) >= self.restored_file_max_files:
                break
            if isinstance(m.get("file_read_path"), str): # 方式1：从之前 _tool_result_budget 记录的 file_read_path 字段获取
                p = str(m.get("file_read_path", "")).strip()
                if p and p not in paths:
                    paths.append(p)
                continue
            name = str(m.get("name") or m.get("tool_name") or "") # 方式2：识别 file_read 工具调用，从其内容中提取路径
            if str(m.get("role", "")) in {"tool", "function"} and name == "file_read":
                p = self._extract_file_path_from_file_read_content(str(m.get("content", "")))
                if p and p not in paths:
                    paths.append(p)
        return list(reversed(paths))

    def _restore_recent_files(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        '''恢复最近读取过的最新的文件'''
        from claude_agent.tools.core_tools.file_read_tool import FileReadTool

        paths = self._extract_recent_file_reads(messages)
        if not paths:
            return []

        restored: list[dict[str, Any]] = []
        tool = FileReadTool()
        max_chars = int(self.restored_file_max_tokens * 4)
        max_bytes = int(self.restored_file_max_tokens * 4)
        for p in paths:
            try: # 通过工具读取，自动享受工具的截断和编码处理
                raw = tool.run(file_path=p, max_chars=max_chars, max_bytes=max_bytes)
            except Exception:
                continue
            try: # 解析工具返回的 JSON
                data = json.loads(raw)
            except Exception:
                data = {"kind": "error", "path": p, "content": raw}
            kind = str(data.get("kind", ""))
            if kind == "text":
                text = str(data.get("content", ""))
                restored.append({"role": "system", "content": "\n".join(["[Restored file]", f"path: {p}", "", text])})
            else:
                mime = str(data.get("mime", ""))
                truncated = bool(data.get("truncated", False))
                restored.append( # 二进制文件的处理：只记录元信息，不嵌入内容
                    {
                        "role": "system",
                        "content": "\n".join(
                            [
                                "[Restored file]",
                                f"path: {p}",
                                f"kind: {kind or 'binary'}",
                                f"mime: {mime or '-'}",
                                f"truncated: {truncated}",
                            ]
                        ),
                    }
                )
        return restored

    def _heavy_summary(self, messages: list[dict[str, Any]]) -> str:
        '''重型摘要方法'''
        from claude_agent.multi_agent.sub_agent import SubAgent

        conversation = "\n".join(f"{m.get('role','')}: {m.get('content','')}".strip() for m in messages)
        prompt = "\n".join(
            [
                "You are a compression agent.",
                "Summarize the conversation into exactly 9 fixed sections:",
                "①核心请求 ②关键概念 ③涉及文件列表 ④代码错误与修复 ⑤问题解决过程 ⑥所有用户消息 ⑦代办事项 ⑧档期按工作 ⑨下一步计划",
                "Output format must be one line per section: '①核心请求: ...'",
                "Total output must be <= 20K tokens.",
                "",
                "Conversation:",
                conversation,
            ]
        )
        agent = SubAgent()
        return agent.run(prompt)

    def _auto_compact(self, messages: list[dict[str, Any]], *, user_id: str, session_id: str) -> list[dict[str, Any]]:
        '''策略三：自动压缩'''
        from claude_agent.memory.auto_memory import AutoMemory

        AutoMemory(storage_root=self.storage_root, user_id=user_id).schedule_write( # 压缩前调用AutoMemory进行长期记忆摘要
            [dict(role=str(m.get("role", "")), content=str(m.get("content", ""))) for m in messages],
            session_id=session_id,
            force=True,
        )
        summary = self._load_session_summary(user_id, session_id).strip() # 1. 尝试加载会话摘要（来自 SessionMemory）
        tail = self._take_tail_by_token_budget(messages) # 2. 保留尾部消息（10K-40K Token）
        if summary: # 3. 组合：摘要 + 尾部消息
            compacted = [{"role": "system", "content": "[Session summary]\n" + summary}] + tail
            # 压缩完成后使用AutoMemory重置索引
            AutoMemory(storage_root=self.storage_root, user_id=user_id).bump_epoch_and_reset_cursor(len(compacted))
        else:
            try:
                heavy = self._heavy_summary(messages) # 4. 轻量失败，使用重型摘要
                compacted = [{"role": "system", "content": "[Session summary]\n" + heavy}] + tail
                AutoMemory(storage_root=self.storage_root, user_id=user_id).bump_epoch_and_reset_cursor(len(compacted))
            except:
                compacted = messages
        compacted.extend(self._restore_recent_files(messages)) # 5. 恢复最近读取的文件
        return compacted

    def _blocking_limit(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        '''策略四：强制截断'''
        out = list(messages)
        while self.total_message_tokens(out) > self.message_token_budget and len(out) > 1: # 从头部开始丢弃消息，直到 Token 数符合预算
            out = out[1:]
        if self.total_message_tokens(out) <= self.message_token_budget:
            return out

        final: list[dict[str, Any]] = [] # 如果只剩一条消息仍然超限，截断该消息内容
        for m in out:
            msg = dict(m)
            content = str(msg.get("content", ""))
            if estimate_tokens(content) > self.message_token_budget:
                msg["content"] = self.snip(content, max_chars=self.message_token_budget * 4)
            final.append(msg)
        return final
