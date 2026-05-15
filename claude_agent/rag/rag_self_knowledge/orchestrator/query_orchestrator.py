from __future__ import annotations

from typing import Any

from ..config.settings import Embedder, Settings
from ..models.retrieval import SearchResult
from ..orchestrator.rrf import reciprocal_rank_fusion
from ..storage.object_store.base import ObjectStore
from ..storage.relational.sqlite import SQLiteRelationalStore
from ..storage.vector.base import VectorStore
from ..utils.hashing import sha256_text

'''
用户查询
    ↓
[1] 向量化查询
    ↓
┌─────────────────────────────────┐
│         多路并行召回              │
├─────────────────────────────────┤
│ 直接chunk检索 │ 摘要检索 │子问题检索 │
│ (direct)    │(summary)│ (subq)  │
└─────────────────────────────────┘
    ↓              ↓           ↓
  ID列表        摘要ID列表   问题ID列表
    ↓              ↓           ↓
    ↓        查询关联chunk   查询关联chunk
    ↓              ↓           ↓
    └──────────┬──┴───────────┘
               ↓
    [2] RRF融合排序
               ↓
    [3] 候选chunk去重取top_k
               ↓
    [4] 阈值过滤和MMR多样性
               ↓
    [5] 查询关系库获取text_ref
               ↓
    [6] 从对象存储读取原文
               ↓
    [7] 合并元数据，返回结果
'''

class QueryOrchestrator:
    '''
    RAG系统的查询编排器，负责智能检索和融合多路召回结果
    '''
    def __init__(
        self,
        *,
        kb_name: str, # 知识库名称
        relational: SQLiteRelationalStore, # 关系库实例
        vector: VectorStore, # 向量库实例
        object_store: ObjectStore, # 对象存储实例
        embedder: Embedder, # 向量化编码器
        settings: Settings, # 配置对象
    ) -> None:
        self._kb_name = kb_name
        self._relational = relational
        self._vector = vector
        self._object_store = object_store
        self._embedder = embedder
        self._settings = settings

    def search(
        self, *, query: str, filters: dict[str, Any] | None, top_k: int
    ) -> list[SearchResult]:
        '''核心检索逻辑
        Args:
            query：用户查询字符串
            filters：过滤条件（如{"author": "张三"}）
            top_k：返回前K个结果
        '''
        query_vec = self._embedder.embed(query) # 将查询文本向量化，用于相似度计算
        kb_id = self._relational.ensure_kb(kb_name=self._kb_name)
        kb_config = self._relational.resolve_kb_config(
            kb_id=kb_id, defaults=_settings_to_kb_config(self._settings)
        )

        where = {"kb_name": self._kb_name} # 构建过滤条件

        ranked_lists: list[list[str]] = []  # ranked_lists是一个二维列表，每个子列表是一路召回的结果ID（按相关度排序）
        recall_k = max(1, top_k * 5) # 先多召回一些，后面要筛选过滤

        direct_hits = self._vector.query( # 1. 第一路召回：直接chunk检索
            collection=f"{_collection_prefix(self._kb_name)}_direct",
            query_embedding=query_vec,
            top_k=recall_k,
            where=where,
        )
        ranked_lists.append([h.item_id for h in direct_hits])

        if bool(kb_config.get("enable_summary_index")):
            summary_hits = self._vector.query( # 2. 第二路召回：在摘要向量库中检索，找到相关的摘要
                collection=f"{_collection_prefix(self._kb_name)}_summary",
                query_embedding=query_vec,
                top_k=recall_k,
                where=where,
            )
            summary_ids = [h.item_id for h in summary_hits] # 提取摘要ID列表
            summary_map = self._relational.get_summary_chunk_ids(summary_ids=summary_ids) # 查询关系库，获取每个摘要关联的chunk ID列表
            ranked: list[str] = [] # 将摘要关联的chunk展开为chunk ID列表
            seen: set[str] = set()
            for sid in summary_ids:
                for cid in summary_map.get(sid, []):
                    if cid not in seen:
                        ranked.append(cid)
                        seen.add(cid)
            ranked_lists.append(ranked)

        if bool(kb_config.get("enable_subq_index")):
            subq_hits = self._vector.query( # 3. 第三路召回：子问题检索
                collection=f"{_collection_prefix(self._kb_name)}_subq",
                query_embedding=query_vec,
                top_k=recall_k,
                where=where,
            )
            question_ids = [h.item_id for h in subq_hits]
            subq_map = self._relational.get_subq_chunk_ids(question_ids=question_ids) # 查询子问题到chunk的映射
            ranked: list[str] = [] # 将子问题映射到chunk，去重后添加到融合列表
            seen: set[str] = set()
            for qid in question_ids:
                cid = subq_map.get(qid)
                if cid and cid not in seen:
                    ranked.append(cid)
                    seen.add(cid)
            ranked_lists.append(ranked)

        direct_meta_by_id = {h.item_id: dict(h.metadata) for h in direct_hits} # chunk_id → 元数据
        direct_score_by_id = {h.item_id: float(h.score) for h in direct_hits} # chunk_id → 相似度分数

        if len(ranked_lists) == 1: # if: 只有一路召回（仅直接chunk），直接使用直接检索的分数和结果
            fused_scores = direct_score_by_id
            candidate_chunk_ids = ranked_lists[0][:recall_k]
        else: # else: 多路召回时，使用RRF算法融合
            fused_scores = reciprocal_rank_fusion(ranked_lists, k=60)
            candidate_chunk_ids = [
                cid
                for cid, _ in sorted(
                    fused_scores.items(), key=lambda kv: kv[1], reverse=True
                )
            ][:recall_k]

        candidate_chunk_ids, doc_meta_by_chunk_id = self._relational.filter_chunk_ids( # 过滤候选chunk，根据过滤条件
            chunk_ids=candidate_chunk_ids, filters=filters
        )

        min_score = float(kb_config.get("min_score", 0.0) or 0.0) # 使用阈值过滤，把相关性低的向量过滤
        if min_score > 0.0:
            candidate_chunk_ids = [
                cid for cid in candidate_chunk_ids if float(fused_scores.get(cid, 0.0)) >= min_score
            ]

        if bool(kb_config.get("enable_diversity", True)): # 使用多样性算法MMR提高召回的文本的多样性
            key_name = str(kb_config.get("diversity_key", "doc_id") or "doc_id")
            candidate_chunk_ids = _diversify(
                candidate_chunk_ids,
                meta_by_chunk_id=doc_meta_by_chunk_id,
                top_k=top_k,
                key_name=key_name,
            )
        else:
            candidate_chunk_ids = candidate_chunk_ids[:top_k]

        refs = self._relational.get_chunk_refs(chunk_ids=candidate_chunk_ids) # 批量查询候选chunk的引用信息（对象存储路径等）

        results: list[SearchResult] = []
        for chunk_id in candidate_chunk_ids:
            ref = refs.get(chunk_id, {}).get("text_ref")
            text = ""
            if ref:
                try:
                    text = self._object_store.get_text(ref=ref) # 遍历候选chunk，从对象存储读取实际文本
                except Exception:
                    text = ""

            meta = direct_meta_by_id.get(chunk_id, {})
            meta.setdefault("kb_name", self._kb_name)
            if refs.get(chunk_id):
                meta.setdefault("doc_id", refs[chunk_id].get("doc_id"))
                meta.setdefault("chunk_index", refs[chunk_id].get("chunk_index"))
                meta.setdefault("text_ref", refs[chunk_id].get("text_ref"))
            if doc_meta_by_chunk_id.get(chunk_id):
                meta.update(doc_meta_by_chunk_id[chunk_id])

            results.append(
                SearchResult(
                    chunk_id=chunk_id,
                    doc_id=str(meta.get("doc_id")),
                    score=float(fused_scores.get(chunk_id, 0.0)),
                    text=text,
                    metadata=meta,
                )
            )

        return results


def _diversify(
    chunk_ids: list[str],
    *,
    meta_by_chunk_id: dict[str, dict[str, Any]],
    top_k: int,
    key_name: str,
) -> list[str]:
    '''对chunk ID列表进行多样化重排
    Args:
        chunk_ids：待处理的chunk ID列表（按相关度排序）
        meta_by_chunk_id：每个chunk的元数据字典
        top_k：需要返回的最大数量
        key_name：用于分组的键名（如"author"、"source"）
    Returns:
        多样化排序后的chunk ID列表
    '''
    if top_k <= 0:
        return []
    if len(chunk_ids) <= 1:
        return chunk_ids[:top_k]

    buckets: dict[str, list[str]] = {} # 分组字典，键为分组标识，值为该组的chunk ID列表
    bucket_order: list[str] = [] # 保持分组首次出现的顺序
    for cid in chunk_ids:
        meta = meta_by_chunk_id.get(cid, {})
        key = meta.get(key_name) or meta.get("doc_id") or meta.get("source") or "unknown" # 使用指定的key_name（如"author"）| 如果没有，使用文档ID（"doc_id"）| 如果没有，使用来源（"source"）| 最后使用"unknown"
        key = str(key)
        if key not in buckets:
            buckets[key] = []
            bucket_order.append(key)
        buckets[key].append(cid)


    '''
    这是一个轮询（Round-robin）算法：
    1. 外层循环：继续直到收集够top_k个结果
    2. 内层循环：按bucket_order顺序，从每个桶中取一个chunk
    3. pop(0)：从桶的头部取出（保持桶内的原始顺序）
    4. progressed标志：检查是否有进展（防止死循环）
    5. 提前退出：达到top_k立即返回
    '''
    out: list[str] = [] # 存储最后多样性筛选的结果
    while len(out) < top_k:
        progressed = False
        for k in bucket_order:
            bucket = buckets.get(k)
            if bucket:
                out.append(bucket.pop(0))
                progressed = True
                if len(out) >= top_k:
                    break
        if not progressed:
            break
    return out


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
