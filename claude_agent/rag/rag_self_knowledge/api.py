from __future__ import annotations

"""
对外暴露的“调用层”函数接口。

本模块对应 structure.md 的“调用层”，目标是：
- 仅提供稳定的函数签名（add_documents / search_knowledge）
- 隐藏内部模块拆分与后端实现细节
- 允许调用方按需注入 settings/services 以替换存储与模型能力
"""

from dataclasses import asdict
from typing import Any, Iterable, Mapping, Sequence

from .config.settings import RagServices, Settings, create_default_services
from .models.document import DocumentMetadata
from .models.retrieval import SearchResult
from .orchestrator.ingest_orchestrator import IngestOrchestrator
from .orchestrator.query_orchestrator import QueryOrchestrator


def add_documents(
    kb_name: str,
    docs: Sequence[str],
    metadatas: Sequence[DocumentMetadata] | None = None,
    *,
    settings: Settings | None = None,
    services: RagServices | None = None,
) -> list[str]:
    """
    将一批文档写入指定知识库（入库流程）。

    参数：
    - kb_name：知识库名称。用于：
      - 生成向量库 collection 名（如 {kb_name}_direct）
      - 生成对象存储目录前缀（如 blobs/{kb_name}/...）
      - 作为多租户隔离键参与过滤
    - docs：待入库文档正文列表（每个元素代表一篇文档的全文字符串）。
    - metadatas：与 docs 一一对应的文档元数据列表；可为 None（表示所有文档无额外元数据）。
    - settings：运行配置（默认 SQLite 路径、blobs 根目录、chunk 参数等）。当 services 未显式传入时生效。
    - services：依赖注入容器，包含关系库/向量库/对象存储/分块器/向量化器等。
      - 传入该参数可覆盖默认实现，便于切换到 PostgreSQL/Qdrant/MinIO/真实 Embedding。

    返回：
    - 入库后解析得到的 doc_id 列表（与 docs 同序）。
    """
    if services is None:
        # 未注入 services 时，创建一套默认服务：
        # - SQLite 关系库（存元数据/映射/入库流水）
        # - 本地文件系统对象存储（落盘 chunk 文本）
        # - 内存向量库（用于最小可运行闭环）
        # - 固定长度 Chunker
        # - HashingEmbedder（无外部依赖的伪 embedding）
        services = create_default_services(settings=settings)

    # 入库编排器负责将多个核心模块串起来：
    # docs → chunker → object_store/relational/vector → ingest_runs 状态更新
    orchestrator = IngestOrchestrator(
        kb_name=kb_name,
        relational=services.relational,
        vector=services.vector,
        object_store=services.object_store,
        chunker=services.chunker,
        embedder=services.embedder,
        llm_client=services.llm_client,
        settings=services.settings,
    )
    # 执行入库并返回 doc_id 列表
    return orchestrator.ingest(docs=docs, metadatas=metadatas)

def list_knowledge_bases(
    *,
    settings: Settings | None = None,
    services: RagServices | None = None,
) -> list[dict[str, Any]]:
    """
    查询当前已存在的知识库列表及其描述信息。

    返回：
    - [{"kb_id": "...", "kb_name": "...", "description": "...|None"}, ...]
    """
    if services is None:
        services = create_default_services(settings=settings)
    return services.relational.list_knowledge_bases()

def search_knowledge(
    kb_name: str,
    query: str,
    *,
    filters: Mapping[str, Any] | None = None,
    top_k: int = 5,
    settings: Settings | None = None,
    services: RagServices | None = None,
) -> list[SearchResult]:
    """
    在指定知识库中检索与 query 相关的内容（查询流程）。

    参数：
    - kb_name：知识库名称。用于选择向量库 collection 并做多租户隔离过滤。
    - query：用户查询文本（问题/关键词/描述）。
    - filters：过滤条件（等值过滤为主）。当前最小实现会把 filters 合并进向量库 where。
      - 典型字段：author/source/created_date/doc_id 等（见 table.md 的 metadata 建议字段）。
      - 复杂过滤（tags IN、JSONB 查询、正则等）应由 SQL 层实现；后续可在 MetadataFilter 中增强。
    - top_k：返回结果条数上限。
    - settings：运行配置（当 services 未显式传入时用于创建默认依赖）。
    - services：依赖注入容器，允许替换向量库/关系库/对象存储/Embedding 等实现。

    返回：
    - SearchResult 列表，包含 chunk_id/doc_id/score/text/metadata。
    """
    if services is None:
        # 与 add_documents 同理：未注入时创建默认服务，便于本地最小运行与回归。
        services = create_default_services(settings=settings)

    # 查询编排器负责串联：embedding → 向量库检索 → 关系库补信息 → 对象存储回读正文（如有）
    orchestrator = QueryOrchestrator(
        kb_name=kb_name,
        relational=services.relational,
        vector=services.vector,
        object_store=services.object_store,
        embedder=services.embedder,
        settings=services.settings,
    )
    normalized_filters: dict[str, Any] | None = None
    if filters is not None:
        # 统一成可变 dict，便于后续流程追加/改写过滤条件
        normalized_filters = dict(filters)
    # 执行检索并返回结果
    return orchestrator.search(query=query, filters=normalized_filters, top_k=top_k)


def _as_dicts(items: Iterable[Any]) -> list[dict[str, Any]]:
    """
    将任意可迭代对象尽可能转换为 dict 列表（用于调试/序列化的工具函数）。

    规则：
    - dataclass：使用 asdict() 展开
    - dict：浅拷贝
    - 其他：包装为 {"value": item}
    """
    out: list[dict[str, Any]] = []
    for item in items:
        if hasattr(item, "__dataclass_fields__"):
            # dataclass 实例：展开为普通 dict
            out.append(asdict(item))
        elif isinstance(item, dict):
            # 已是 dict：浅拷贝一份，避免外部修改影响内部引用
            out.append(dict(item))
        else:
            # 兜底：保持可序列化形态
            out.append({"value": item})
    return out
