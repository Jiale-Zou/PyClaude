from __future__ import annotations

from dataclasses import asdict # 将dataclass对象转换为字典
from typing import Any, Mapping, Sequence

from ..config.settings import Embedder, LLMClient, Settings
from ..core.chunking.base import BaseChunker
from ..models.chunk import Chunk
from ..models.document import DocumentMetadata
from ..storage.object_store.base import ObjectStore
from ..storage.relational.sqlite import SQLiteRelationalStore
from ..storage.vector.base import VectorItem, VectorStore
from ..utils.hashing import sha256_text

'''
输入文档
    ↓
[1] 确保知识库存在 (ensure_kb)
    ↓
[2] 开始导入任务 (start_ingest_run)
    ↓
[3] 对每个文档：
    ├─ 存储文档元数据 (upsert_document)
    ├─ 分块 (chunker.chunk)
    └─ 对每个chunk：
        ├─ 存原文到对象存储 (put_text)
        ├─ 存chunk元数据 (upsert_chunk)
        ├─ 向量化 (embedder.embed)
        └─ 准备向量项 (VectorItem)
    ↓
[4] 批量插入向量库 (vector.upsert)
    ↓
[5] 可选：摘要索引 (_index_summaries)
    ↓
[6] 可选：子问题索引 (_index_subquestions)
    ↓
[7] 完成导入任务 (finish_ingest_run)
'''


class IngestOrchestrator:
    '''
    定义文档导入编排器类，负责协调整个导入流程
    '''
    def __init__(
        self,
        *,
        kb_name: str, # 知识库名称
        relational: SQLiteRelationalStore, # 关系库实例
        vector: VectorStore, # 向量库实例
        object_store: ObjectStore, # 对象存储实例
        chunker: BaseChunker, # 文档分块器
        embedder: Embedder,  # 向量化编码器
        llm_client: LLMClient,  # LLM客户端
        settings: Settings, # 配置对象
    ) -> None:
        self._kb_name = kb_name
        self._relational = relational
        self._vector = vector
        self._object_store = object_store
        self._chunker = chunker
        self._embedder = embedder
        self._llm_client = llm_client
        self._settings = settings

    def ingest(
        self, *, docs: Sequence[str], metadatas: Sequence[DocumentMetadata] | None
    ) -> list[str]:
        '''主入口方法，导入文档到知识库
        Args:
            docs：文档文本列表
            metadatas：元数据列表（可为None）
        Returns:
            生成的文档ID列表
        '''
        kb_id = self._relational.ensure_kb(kb_name=self._kb_name) # 确保知识库存在，返回知识库ID
        kb_config = self._relational.resolve_kb_config( # 知识库配置获取：每个知识库可以有独立的配置（摘要开关、分块参数等），使用默认配置兜底
            kb_id=kb_id, defaults=_settings_to_kb_config(self._settings)
        )
        ingest_id = self._relational.start_ingest_run(kb_id=kb_id, request_id=None) # 开始一个导入任务，记录开始时间、状态为"running"，返回任务ID，用于追踪进度

        resolved_doc_ids: list[str] = [] # 初始化空列表，用于存储处理后的文档ID
        try:
            metas = list(metadatas) if metadatas is not None else [] # 将元数据转换为列表，如果为None则创建空列表
            while len(metas) < len(docs): # 1. 如果元数据数量少于文档数量，用默认元数据补齐
                metas.append(DocumentMetadata())

            for i, (doc_text, meta) in enumerate(zip(docs, metas, strict=True), start=1):
                default_source = f"custom://{self._kb_name}/{i}" # 生成默认来源标识，格式如 custom://my_kb/1
                source = meta.source or default_source
                existing_doc = self._relational.get_document_by_source(kb_id=kb_id, source=source) # 通过source看看能不能获取到文档内容
                new_doc_hash = sha256_text(doc_text) # 计算文档内容哈希
                doc_id, _doc_hash = self._relational.upsert_document( # 2. 将文档信息存入关系库，返回文档ID和内容哈希
                    kb_id=kb_id,
                    doc_text=doc_text,
                    metadata=meta,
                    default_source=default_source,
                )
                resolved_doc_ids.append(doc_id)

                existing_chunk_ids = self._relational.get_chunk_ids_by_doc(doc_id=doc_id) # 文档之前的chunk_ids
                if (
                    existing_doc is not None # 文档之前存在
                    and existing_doc.get("content_hash") == new_doc_hash # 且文档Hash没变
                    and existing_chunk_ids # 且有已存在的的文档chunks
                ):
                    need_summary = bool(kb_config.get("enable_summary_index")) and self._relational.count_summaries_by_doc(doc_id=doc_id) == 0
                    need_subq = bool(kb_config.get("enable_subq_index")) and self._relational.count_subq_by_doc(doc_id=doc_id) == 0
                    if not need_summary and not need_subq: # 检查是否需要补充摘要和子问题，Yes就是不需要，跳过
                        continue

                    chunk_ids = [existing_chunk_ids[i] for i in sorted(existing_chunk_ids)] # 若需要，则先更具chunk_ids取到对应的真实原文
                    refs = self._relational.get_chunk_refs(chunk_ids=chunk_ids)
                    chunks: list[Chunk] = []
                    for cid in chunk_ids:
                        ref = refs.get(cid, {}).get("text_ref")
                        text = ""
                        if ref:
                            try:
                                text = self._object_store.get_text(ref=ref)
                            except Exception:
                                text = ""
                        chunks.append(
                            Chunk(
                                chunk_id=cid,
                                doc_id=doc_id,
                                chunk_index=int(refs.get(cid, {}).get("chunk_index", 0)),
                                text=text,
                                content_hash=sha256_text(text),
                                text_ref=ref,
                            )
                        )

                    if need_summary: # 需要摘要则生成摘要
                        self._index_summaries(
                            doc_id=doc_id,
                            chunks=chunks,
                            group_size=int(kb_config.get("summary_group_size", 5)),
                            max_chars=int(kb_config.get("summary_max_chars", 800)),
                        )
                    if need_subq: # 需要子问题则生成子问题
                        self._index_subquestions(
                            doc_id=doc_id,
                            chunks=chunks,
                            per_chunk=int(kb_config.get("subq_per_chunk", 3)),
                        )
                    continue

                raw_chunks = self._chunker.chunk( # 3. 将文档切分成多个chunk
                    doc_text,
                    doc_id=doc_id,
                    metadata=_metadata_for_chunking(meta, kb_name=self._kb_name),
                )

                self._relational.deactivate_chunks_by_doc(doc_id=doc_id) # 根性文档是，若文档存在旧的chunk，先将旧的chunk标记为is_active=False，只认 is_active=1

                vector_items: list[VectorItem] = [] # 初始化向量项列表，用于批量插入向量库
                chunks: list[Chunk] = []
                for ch in raw_chunks:
                    stable_chunk_id = existing_chunk_ids.get(ch.chunk_index, ch.chunk_id) # 若chunk_id之前存在过，使用之前的chunk_id
                    chunks.append(
                        Chunk(
                            chunk_id=stable_chunk_id,
                            doc_id=doc_id,
                            chunk_index=ch.chunk_index,
                            text=ch.text,
                            content_hash=ch.content_hash,
                            text_ref=None,
                        )
                    )
                    key = f"{self._kb_name}/chunks/{doc_id}/{stable_chunk_id}.txt" # 生成对象存储的键（路径），格式如 my_kb/chunks/doc_123/chunk_456.txt
                    ref = self._object_store.put_text(key=key, text=ch.text) # 将chunk原文存入对象存储，返回引用路径
                    self._relational.upsert_chunk( # 将chunk元信息存入关系库，包括引用路径
                        doc_id=doc_id,
                        chunk_id=stable_chunk_id,
                        chunk_index=ch.chunk_index,
                        content_hash=ch.content_hash,
                        text_ref=ref,
                    )

                    embedding = self._embedder.embed(ch.text) # 4. 将chunk文本向量化，得到embedding向量
                    vector_items.append(
                        VectorItem( # 创建向量项，包含
                            item_id=stable_chunk_id, # 唯一标识（chunk_id）
                            embedding=embedding, # 向量表示
                            document=ch.text, # 原始文本
                            metadata={ # 附加信息（用于过滤和展示）
                                "kb_name": self._kb_name,
                                "doc_id": doc_id,
                                "chunk_index": ch.chunk_index,
                                "source": source,
                                "author": meta.author,
                                "created_date": meta.created_date,
                                "content_hash": ch.content_hash,
                                "text_ref": ref,
                            },
                        )
                    )

                self._vector.upsert( # 5. 批量插入向量库：将所有chunk的向量批量插入向量库
                    collection=f"{_collection_prefix(self._kb_name)}_direct", items=vector_items
                )
                # 6. 根据配置决定是否建立摘要索引和子问题索引
                if bool(kb_config.get("enable_summary_index")):
                    self._index_summaries(
                        doc_id=doc_id,
                        chunks=chunks,
                        group_size=int(kb_config.get("summary_group_size", 5)),
                        max_chars=int(kb_config.get("summary_max_chars", 800)),
                    )
                if bool(kb_config.get("enable_subq_index")):
                    self._index_subquestions(
                        doc_id=doc_id,
                        chunks=chunks,
                        per_chunk=int(kb_config.get("subq_per_chunk", 3)),
                    )

            self._relational.finish_ingest_run(ingest_id=ingest_id, status="committed") # 7.1 标记导入任务为成功
            return resolved_doc_ids
        except Exception as e:
            self._relational.finish_ingest_run( # 7.2 发生异常时，标记任务失败并重新抛出异常
                ingest_id=ingest_id, status="failed", error_message=str(e)
            )
            raise

    def _index_summaries(self, *, doc_id: str, chunks, group_size: int, max_chars: int) -> None:
        '''摘要索引'''
        group_size = max(1, int(group_size))
        max_chars = max(1, int(max_chars))

        groups: list[list] = []
        current: list = []
        for ch in chunks: # 将chunk按指定大小分组: 例如group_size=3，则每3个chunk生成一个摘要
            current.append(ch)
            if len(current) >= group_size:
                groups.append(current)
                current = []
        if current:
            groups.append(current)

        items: list[VectorItem] = []
        for group in groups:
            joined = "\n".join(c.text for c in group) # 合并组内文本，截取前max_chars字符作为摘要（需要后期替换）
            summary_text = self._llm_client.summarize(joined, max_chars=max_chars) # 使用llm生成摘要
            group_key = ",".join(c.chunk_id for c in group)
            summary_id = "sum_" + sha256_text(f"{doc_id}|{group_key}")[:32] # 基于内容生成确定性的ID，保证幂等性
            content_hash = sha256_text(summary_text)
            key = f"{self._kb_name}/summaries/{doc_id}/{summary_id}.txt" # 将摘要存入对象存储
            ref = self._object_store.put_text(key=key, text=summary_text)

            chunk_ids_payload = [ # 存储摘要元数据，记录关联的chunk列表（记录摘要由哪些chunk生成）
                {"chunk_id": c.chunk_id, "chunk_index": c.chunk_index} for c in group
            ]
            self._relational.upsert_summary(
                summary_id=summary_id,
                doc_id=doc_id,
                text_ref=ref,
                chunk_ids=chunk_ids_payload,
                content_hash=content_hash,
            )

            embedding = self._embedder.embed(summary_text) # 向量化摘要并准备插入向量库
            items.append(
                VectorItem(
                    item_id=summary_id,
                    embedding=embedding,
                    document=summary_text,
                    metadata={
                        "kb_name": self._kb_name,
                        "doc_id": doc_id,
                        "content_hash": content_hash,
                        "text_ref": ref,
                    },
                )
            )

        self._vector.upsert(collection=f"{_collection_prefix(self._kb_name)}_summary", items=items)

    def _index_subquestions(self, *, doc_id: str, chunks, per_chunk: int) -> None:
        '''子问题索引'''
        per_chunk = max(1, int(per_chunk))
        items: list[VectorItem] = []
        for ch in chunks:
            prompts = self._llm_client.generate_subquestions(ch.text, n=per_chunk) # 使用llm为每个chunk生成子问题列表
            for q in prompts: # 存储子问题与chunk的映射关系
                question_id = "q_" + sha256_text(f"{doc_id}|{ch.chunk_id}|{q}")[:32]
                content_hash = sha256_text(q)
                self._relational.upsert_subq_mapping(
                    question_id=question_id,
                    doc_id=doc_id,
                    chunk_id=ch.chunk_id,
                    question_text=q,
                    content_hash=content_hash,
                )

                embedding = self._embedder.embed(q) # 向量化子问题并插入 {知识库名}_subq 集合
                items.append(
                    VectorItem(
                        item_id=question_id,
                        embedding=embedding,
                        document=q,
                        metadata={
                            "kb_name": self._kb_name,
                            "doc_id": doc_id,
                            "chunk_id": ch.chunk_id,
                            "content_hash": content_hash,
                        },
                    )
                )

        self._vector.upsert(collection=f"{_collection_prefix(self._kb_name)}_subq", items=items)


def _metadata_for_chunking(meta: DocumentMetadata, *, kb_name: str) -> Mapping[str, Any]:
    '''将DocumentMetadata转换为字典，并添加知识库名称'''
    base = asdict(meta)
    base["kb_name"] = kb_name
    return base


def _settings_to_kb_config(settings: Settings) -> dict[str, Any]:
    '''设置默认的知识库配置参数json_config'''
    return {
        "enable_summary_index": bool(settings.enable_summary_index),
        "enable_subq_index": bool(settings.enable_subq_index),
        "summary_group_size": int(settings.summary_group_size),
        "summary_max_chars": int(settings.summary_max_chars),
        "subq_per_chunk": int(settings.subq_per_chunk),
        "min_score": float(settings.min_score),
        "enable_diversity": bool(settings.enable_diversity),
        "diversity_key": str(settings.diversity_key),
    }


def _collection_prefix(kb_name: str) -> str:
    return "kb_" + sha256_text(str(kb_name))[:32]
