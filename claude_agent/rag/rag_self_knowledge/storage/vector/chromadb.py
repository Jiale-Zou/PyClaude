from __future__ import annotations

from pathlib import Path

import chromadb
from chromadb.config import Settings as ChromaSettings
from dataclasses import dataclass
from typing import Any, Mapping

from .base import VectorItem, VectorQueryResult, VectorStore


@dataclass
class ChromaVectorStore(VectorStore):
    """
    ChromaDB 向量存储实现

    特点：
    - 持久化存储（默认 ./chroma_data 目录）
    - 支持元数据过滤（where 条件）
    - 支持余弦相似度检索
    - 自动处理 embedding 归一化
    """

    # ChromaDB 客户端
    _client: chromadb.ClientAPI
    # 是否持久化
    _persist_directory: str | None
    # 集合缓存（避免重复获取）
    _collections: dict[str, chromadb.Collection]

    def __init__(
            self,
            persist_directory: str = str(Path(__file__).parent.parent.parent / "storage_data" / "vector_data"),
            collection_metadata: dict[str, Any] | None = None,
    ) -> None:
        """
        初始化 ChromaDB 向量存储

        参数：
        - persist_directory: 数据持久化目录（None 表示内存模式，重启后数据丢失）
        - collection_metadata: 集合级别的元数据配置（如距离函数）
        """
        # 配置 ChromaDB 客户端
        if persist_directory:
            # 持久化模式
            self._client = chromadb.PersistentClient(
                path=persist_directory
            )
        else:
            # 内存模式（测试用）
            self._client = chromadb.EphemeralClient()

        self._persist_directory = persist_directory
        self._collections = {}
        self._default_metadata = collection_metadata or {
            "hnsw:space": "cosine"  # 使用余弦相似度
        }

    def _get_collection(self, collection_name: str) -> chromadb.Collection:
        """获取或创建集合（ChromaDB 中 collection 类似表的概念）"""
        if collection_name not in self._collections:
            # 优先使用 get_or_create_collection（不同 Chroma 版本的异常类型不一致）
            get_or_create = getattr(self._client, "get_or_create_collection", None)
            if callable(get_or_create):
                collection = get_or_create(
                    name=collection_name,
                    metadata=self._default_metadata,
                )
            else:
                # 尝试获取已存在的集合，不存在则创建
                try:
                    collection = self._client.get_collection(collection_name)
                except Exception:
                    collection = self._client.create_collection(
                        name=collection_name,
                        metadata=self._default_metadata,
                    )
            self._collections[collection_name] = collection
        return self._collections[collection_name]

    def upsert(self, *, collection: str, items: list[VectorItem]) -> None:
        """
        插入或更新向量

        参数：
        - collection: 集合名称（类似表名）
        - items: VectorItem 列表，包含 id、embedding、metadata、document
        """
        if not items:
            return

        col = self._get_collection(collection)

        # 准备批量插入的数据
        ids = [item.item_id for item in items]
        embeddings = [item.embedding for item in items]
        metadatas = [dict(item.metadata) for item in items]
        documents = [item.document for item in items]

        # ChromaDB 的 upsert 操作（存在则更新，不存在则插入）
        col.upsert(
            ids=ids,
            embeddings=embeddings,
            metadatas=metadatas,
            documents=documents,
        )

    def query(
            self,
            *,
            collection: str,
            query_embedding: list[float],
            top_k: int,
            where: Mapping[str, Any] | None = None,
    ) -> list[VectorQueryResult]:
        """
        查询相似向量

        参数：
        - collection: 集合名称
        - query_embedding: 查询向量
        - top_k: 返回 top K 结果
        - where: 元数据过滤条件，例如 {"source": "wikipedia"}

        返回：
        - VectorQueryResult 列表，按相似度从高到低排序
        """
        if top_k <= 0:
            return []

        col = self._get_collection(collection)

        # 执行查询
        # ChromaDB 默认使用余弦相似度（根据 collection metadata 配置）
        results = col.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where=dict(where) if where else None,  # where 条件过滤
        )

        # 转换 ChromaDB 返回格式为 VectorQueryResult
        # ChromaDB 返回格式：
        # {
        #   'ids': [['id1', 'id2', ...]],
        #   'distances': [[0.1, 0.2, ...]],  # 距离值（越小越相似）
        #   'metadatas': [[{...}, {...}]],
        #   'documents': [['doc1', 'doc2', ...]]
        # }

        result_items = []
        if results['ids'] and results['ids'][0]:
            ids = results['ids'][0]
            # ChromaDB 返回的是距离（distance），需要转换为相似度（score）
            # 余弦距离 = 1 - 余弦相似度，所以相似度 = 1 - 距离
            distances = results['distances'][0] if results['distances'] else []
            metadatas = results['metadatas'][0] if results['metadatas'] else []
            documents = results['documents'][0] if results['documents'] else []

            for idx, item_id in enumerate(ids):
                # 转换距离到相似度分数（0-1之间，越高越相似）
                distance = distances[idx] if idx < len(distances) else 1.0
                similarity_score = 1.0 - distance

                result_items.append(
                    VectorQueryResult(
                        item_id=item_id,
                        score=similarity_score,
                        document=documents[idx] if idx < len(documents) else "",
                        metadata=metadatas[idx] if idx < len(metadatas) else {},
                    )
                )

        return result_items

    def delete_collection(self, collection: str) -> None:
        """删除整个集合"""
        try:
            self._client.delete_collection(collection)
            if collection in self._collections:
                del self._collections[collection]
        except Exception:
            pass  # 集合不存在

    def delete(self, *, collection: str, ids: list[str]) -> None:
        """删除指定 ID 的向量"""
        col = self._get_collection(collection)
        col.delete(ids=ids)

    def get_count(self, collection: str) -> int:
        """获取集合中的向量数量"""
        col = self._get_collection(collection)
        return col.count()
