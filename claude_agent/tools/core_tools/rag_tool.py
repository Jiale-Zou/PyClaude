from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from claude_agent.tools.base_tool import BaseTool


class RagToolInput(BaseModel):
    action: str = Field(description="search | list_kbs")
    user_id: str = Field(default="", description="当前用户ID（用于隔离知识库）")
    kb_name: str = Field(default="", description="知识库名称（search 时必填）")
    query: str = Field(default="", description="检索问题（search 时必填）")
    top_k: int = Field(default=5, description="返回条数")


class RagToolOutput(BaseModel):
    ok: bool
    action: str
    user_id: str = ""
    kb_name: str = ""
    results: list[dict[str, Any]] = Field(default_factory=list)
    items: list[dict[str, Any]] = Field(default_factory=list)
    error: str = ""


def _rag_user_root(user_id: str) -> Path:
    return Path(__file__).resolve().parents[2] / "rag" / "storage_data" / user_id


def _rag_user_settings(user_id: str):
    from claude_agent.rag.rag_self_knowledge.config.settings import Settings

    base = _rag_user_root(user_id)
    default = Settings()
    return Settings(
        sqlite_path=base / "relational_data" / "rag_self_knowledge.sqlite3",
        blobs_root=base / "object_data",
        vector_root=base / "vector_data",
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


@dataclass(slots=True)
class RagTool(BaseTool):
    name: str = "rag_tool"
    search_hint: str = "在用户个人知识库（RAG）中检索并返回可追溯结果"
    description: str = "Search the user's personal knowledge bases (RAG) and return traceable results."
    input_schema = RagToolInput
    output_schema = RagToolOutput
    needs_permission: bool = False

    def execute(self, **kwargs: Any) -> BaseModel:
        action = str(kwargs.get("action", "")).strip()
        user_id = str(kwargs.get("user_id", "")).strip() or "default"
        kb_name = str(kwargs.get("kb_name", "")).strip()
        query = str(kwargs.get("query", "")).strip()
        top_k = max(1, int(kwargs.get("top_k", 5)))

        from claude_agent.rag.rag_self_knowledge.api import list_knowledge_bases, search_knowledge
        from claude_agent.rag.rag_self_knowledge.config.settings import create_default_services

        services = create_default_services(settings=_rag_user_settings(user_id))

        if action == "list_kbs":
            items = list_knowledge_bases(services=services)
            return RagToolOutput(ok=True, action=action, user_id=user_id, items=list(items))

        if action != "search":
            return RagToolOutput(ok=False, action=action, user_id=user_id, error="Invalid action.")
        if not kb_name:
            return RagToolOutput(ok=False, action=action, user_id=user_id, error="kb_name is required.")
        if not query:
            return RagToolOutput(ok=False, action=action, user_id=user_id, kb_name=kb_name, error="query is required.")

        results = search_knowledge(kb_name=kb_name, query=query, top_k=top_k, services=services)
        out: list[dict[str, Any]] = []
        for r in results:
            out.append(
                {
                    "chunk_id": getattr(r, "chunk_id", ""),
                    "doc_id": getattr(r, "doc_id", ""),
                    "score": float(getattr(r, "score", 0.0)),
                    "text": getattr(r, "text", ""),
                    "metadata": dict(getattr(r, "metadata", {}) or {}),
                }
            )
        return RagToolOutput(ok=True, action=action, user_id=user_id, kb_name=kb_name, results=out)
