from __future__ import annotations

import json
import os
import platform
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from claude_agent.multi_agent.sub_agent import SubAgent
from claude_agent.utils.token_counter import estimate_tokens


@dataclass(slots=True)
class _SessionAutoMemoryState:
    injected_files: set[str] = field(default_factory=set) # 已经注入到当前会话的记忆文件集合（用set去重，防止重复注入）
    injected_tokens: int = 0 # 已注入内容的总token数，用于预算控制


_SESSION_AUTO_MEMORY: dict[str, _SessionAutoMemoryState] = {} # 全局字典，存储每个会话的记忆状态，key的格式为"user_id:session_id"
_SESSION_AUTO_MEMORY_LOCK = Lock() # 线程锁保护并发访问


@dataclass(frozen=True, slots=True)
class DynamicPromptContext:
    messages: list[dict[str, str]] = field(default_factory=list) # 当前会话的对话历史
    environment: str = "" # 运行环境信息（OS、Python版本、工作目录）
    mcp: str = "" # MCP 服务配置信息
    instructions: str = "" # 用户当前附加的临时指令
    user_id: str = ""
    session_id: str = ""
    storage_root: Path = Path("storage")


def get_environment_info() -> str:
    '''系统环境获取'''
    cwd = os.getcwd()
    info = {
        "os": platform.platform(),
        "python": sys.version.split()[0],
        "cwd": cwd,
    }
    return "\n".join([f"{k}: {v}" for k, v in info.items()])


def _format_messages(messages: list[dict[str, str]]) -> str:
    '''将标准的消息字典列表转换为纯文本格式'''
    lines: list[str] = []
    for m in messages:
        role = str(m.get("role", ""))
        content = str(m.get("content", ""))
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


def load_mcp_info(config_path: Path) -> str:
    '''从 mcp/config.json 读取 MCP 服务配置，检查 enabled 和 services'''
    if not config_path.exists():
        return ""
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return ""
    enabled = bool(data.get("enabled", False))
    services = data.get("services", [])
    if not enabled or not services:
        return ""
    lines: list[str] = ["MCP services:"]
    for s in services:
        name = str(s.get("name", ""))
        url = str(s.get("url", ""))
        on = bool(s.get("enabled", True))
        if not on or not name:
            continue
        lines.append(f"- {name}: {url}")
    return "\n".join(lines)


def load_kb_info(*, user_id: str) -> str:
    '''读取已有知识库的 名称+介绍'''
    uid = str(user_id or "").strip()
    if not uid:
        return ""
    rag_root = Path(__file__).resolve().parent.parent / "rag" / "storage_data" / uid
    if not rag_root.exists():
        return ""

    try:
        from claude_agent.rag.rag_self_knowledge.api import list_knowledge_bases
        from claude_agent.rag.rag_self_knowledge.config.settings import Settings, create_default_services

        default = Settings()
        settings = Settings(
            sqlite_path=rag_root / "relational_data" / "rag_self_knowledge.sqlite3",
            blobs_root=rag_root / "object_data",
            vector_root=rag_root / "vector_data",
            embedding_dim=default.embedding_dim,
            chunk_size=default.chunk_size,
            chunk_overlap=default.chunk_overlap,
            sentence_transformer_model_path=default.sentence_transformer_model_path,
            enable_summary_index=default.enable_summary_index,
            enable_subq_index=default.enable_subq_index,
            summary_group_size=default.summary_group_size,
            summary_max_chars=default.summary_max_chars,
            subq_per_chunk=default.subq_per_chunk,
            min_score=default.min_score,
            enable_diversity=default.enable_diversity,
            diversity_key=default.diversity_key,
        )
        services = create_default_services(settings=settings)
        items = list_knowledge_bases(services=services) or []
    except Exception:
        return ""

    if not items:
        return ""
    lines: list[str] = ["# Knowledge Bases"]
    for it in items[:50]:
        name = str(it.get("kb_name", "")).strip()
        desc = str(it.get("description") or "").strip()
        if not name:
            continue
        if desc:
            lines.append(f"- {name}: {desc}")
        else:
            lines.append(f"- {name}")
    lines.append("")
    lines.append("To search, use rag_tool with action=search and kb_name.")
    return "\n".join(lines).strip()


def _safe_read_text(path: Path, max_chars: int = 200_000) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 20] + "\n...[snip]"


def _extract_yaml_meta(text: str) -> str:
    '''YAML元数据提取'''
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return ""
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return ""
    out = ' | '.join(lines[1:(end+1)])
    return out


def _list_recent_memory_files(memory_dir: Path, limit: int = 200) -> list[Path]:
    '''获取最近的记忆文件'''
    if not memory_dir.exists():
        return []
    files = [p for p in memory_dir.glob("*.md") if p.is_file()]
    files = sorted(files, key=lambda p: p.name) # 按文件名排序（包含时间戳）
    if len(files) <= limit:
        return files
    return files[-limit:] # 取最新的200个


def _latest_user_message(messages: list[dict[str, str]]) -> str:
    '''获取最新用户消息'''
    for m in reversed(messages):
        if str(m.get("role", "")).lower() == "user":
            return str(m.get("content", "")).strip()
    return ""


def _session_key(user_id: str, session_id: str) -> str:
    return f"{user_id}:{session_id}"


def _get_session_state(user_id: str, session_id: str) -> _SessionAutoMemoryState:
    '''获取 user_id:session_id 的 _SessionAutoMemoryState '''
    key = _session_key(user_id, session_id)
    with _SESSION_AUTO_MEMORY_LOCK:
        st = _SESSION_AUTO_MEMORY.get(key)
        if st is None:
            st = _SessionAutoMemoryState()
            _SESSION_AUTO_MEMORY[key] = st
        return st


def _parse_memory_time_from_name(name: str) -> datetime | None:
    if not name.lower().endswith(".md"):
        return None
    stem = name[:-3]
    if not stem.startswith("memory_"):
        return None
    ts = stem[len("memory_") :]
    try:
        dt = datetime.strptime(ts, "%Y%m%d_%H%M%S")
    except Exception:
        return None
    return dt.replace(tzinfo=timezone.utc)


def _age_days(path: Path) -> int | None:
    '''计算记忆年龄 - 用于判断记忆是否过时（超过2天会添加警告）'''
    dt = _parse_memory_time_from_name(path.name)
    if dt is None:
        return None
    now = datetime.now(timezone.utc)
    delta = now - dt
    return int(delta.total_seconds() // 86400) # 转换为天数


def _truncate_to_token_budget(text: str, token_budget: int) -> tuple[str, bool]:
    '''使用二分查找精确控制token数'''
    if token_budget <= 0:
        return ("", True)
    if estimate_tokens(text) <= token_budget:
        return (text, False)
    lo, hi = 0, len(text)
    best = 0
    while lo <= hi:
        mid = (lo + hi) // 2
        cand = text[:mid]
        if estimate_tokens(cand) <= token_budget:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return (text[:best], True)


def _select_relevant_memory_files(*, question: str, meta_summary: str, candidate_files: list[Path]) -> list[str]:
    '''构建提示词，让LLM从候选列表中选择最相关的记忆'''
    if not meta_summary:
        return []
    candidate_names = [p.name for p in candidate_files]
    prompt = "\n".join(
        [
            "You select the most relevant long-term memory files for the user question.",
            "Return ONLY a JSON array of up to 5 items. Each item must be exactly one file name from the candidates.",
            "",
            "User Question:",
            question,
            "",
            "Candidates (filename + YAML metadata summary):",
            meta_summary,
            "",
            "Please return the selected file names from the candidates as List.",
        ]
    )
    try:
        agent = SubAgent()
        raw = agent.run(prompt).strip()
        data = json.loads(raw)
        if isinstance(data, list):
            out: list[str] = []
            seen: set[str] = set()
            for x in data:
                name = str(x).strip()
                if not name or name in seen:
                    continue
                seen.add(name)
                out.append(name)
                if len(out) >= 5:
                    break
            return out
    except Exception:
        pass
    return candidate_names[-5:]


def build_auto_memory_prompt(ctx: DynamicPromptContext) -> str:
    user_id = ctx.user_id.strip()
    session_id = ctx.session_id.strip()
    if not user_id or not session_id:
        return ""

    state = _get_session_state(user_id, session_id)
    if state.injected_tokens >= 60_000: # 总预算60k tokens
        return ""

    memory_dir = ctx.storage_root / user_id / "auto_memory"
    candidates = _list_recent_memory_files(memory_dir, limit=200) # 使用最近200个auto memory
    if not candidates:
        return ""

    meta_lines: list[str] = []
    for p in candidates:
        meta = _extract_yaml_meta(_safe_read_text(p, max_chars=40_000)) # 只读取每个文件的元数据
        if meta == "":
            continue
        filepath_meta = "filename: " + str(p.name) + ' | ' + meta # 拼接文件名+元数据
        meta_lines.append(filepath_meta)
    meta_summary = "\n".join(meta_lines).strip()

    question = _latest_user_message(ctx.messages) # 获取最新的用户问题
    # 用LLM根据用户当前问题选择最相关的5个记忆文件
    selected_names = _select_relevant_memory_files(question=question, meta_summary=meta_summary, candidate_files=candidates)

    existing: dict[str, Path] = {p.name: p for p in candidates if p.exists()} # 过滤已注入的文件
    selected_paths: list[Path] = []
    for name in selected_names:
        p = existing.get(name)
        if p is None:
            continue
        if str(p) in state.injected_files: # 已注入过则跳过
            continue
        selected_paths.append(p)

    if not selected_paths:
        return ""

    remaining = 60_000 - state.injected_tokens
    blocks: list[str] = ["# Auto Memory", ""]
    for p in selected_paths:
        if remaining <= 0:
            break
        raw = _safe_read_text(p)
        budget = min(4000, remaining) # 每个文件最多4000 tokens
        content, truncated = _truncate_to_token_budget(raw, budget)
        if not content.strip():
            continue

        warn = ""
        days = _age_days(p)
        if days is not None and days > 2:
            warn = "[This memory has been days，the fact in it maybe changed, please recheck.]"

        tail = ""
        if truncated:
            tail = f"[..has been truncate, to full read, use read_file_tool to read '{p.as_posix()}']"
        # 构建记忆块
        piece_parts = [f"## {p.name}", f"path: {p.as_posix()}"]
        if warn:
            piece_parts.append(warn)
        piece_parts.extend(["", content.strip()])
        if tail:
            piece_parts.extend(["", tail])
        blocks.append("\n".join(piece_parts).strip())
        blocks.append("")

        injected = estimate_tokens(content)
        state.injected_files.add(str(p))
        state.injected_tokens += injected
        remaining -= injected

    if len(blocks) <= 2:
        return ""
    return "\n".join(blocks).strip()


def build_dynamic_prompt(ctx: DynamicPromptContext) -> str:
    env = ctx.environment.strip() if ctx.environment else get_environment_info() # 1. 环境信息：优先用传入的，否则自动获取
    mcp_block = ctx.mcp.strip() # 2. MCP 信息：优先用传入的，否则从配置文件加载
    if not mcp_block:
        mcp_cfg = Path(__file__).resolve().parent.parent / "mcp" / "config.json"
        mcp_block = load_mcp_info(mcp_cfg)
    kb_info = load_kb_info(user_id=ctx.user_id).strip()
    auto_memory = build_auto_memory_prompt(ctx).strip()
    msgs = _format_messages(ctx.messages).strip() # 3. 格式化对话历史
    parts = [p for p in [env, mcp_block, kb_info, auto_memory, ctx.instructions.strip() if ctx.instructions else "", msgs] if p]
    return "\n\n".join(parts)
