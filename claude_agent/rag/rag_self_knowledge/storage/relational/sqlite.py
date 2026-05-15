from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ...models.document import DocumentMetadata
from ...models.ids import new_id
from ...utils.hashing import sha256_text
from .ddl import SQLITE_DDL


def _now_iso() -> str:
    '''成 UTC 时区的 ISO 格式时间戳'''
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class SQLiteRelationalStore:
    db_path: Path # 数据库文件路径

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path) # 连接数据库
        conn.row_factory = sqlite3.Row # 返回字典风格的行（可用列名访问）
        conn.execute("PRAGMA foreign_keys=OFF") # 关闭外键约束
        return conn

    @contextmanager
    def _connection(self) -> sqlite3.Connection:
        '''建立数据库连接：解决Windows文件锁问题'''
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self) -> None:
        '''初始化表结构'''
        with self._connection() as conn:
            conn.executescript(SQLITE_DDL) # 执行整个建表脚本（幂等）
            cols = [r[1] for r in conn.execute("PRAGMA table_info(chunks)").fetchall()]
            if "is_active" not in cols:
                conn.execute("ALTER TABLE chunks ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1")

    def ensure_kb(self, *, kb_name: str, description: str | None = None) -> str:
        '''确保知识库存在
        1. 如果知识库不存在 → 插入新记录
        2. 如果存在（通过 kb_name 冲突）→ 只更新 updated_at 时间戳
        3. 返回 kb_id（哈希值）
        '''
        kb_id = sha256_text(kb_name)[:32] # 哈希前32字符作为ID
        now = _now_iso()
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO knowledge_bases (kb_id, kb_name, description, config_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(kb_name) DO UPDATE SET updated_at=excluded.updated_at
                """,
                (kb_id, kb_name, description, "{}", now, now),
            )
        return kb_id

    def get_kb_config(self, *, kb_id: str) -> dict[str, Any]:
        '''读取知识库的JSON配置(config_json字段)'''
        with self._connection() as conn:
            row = conn.execute(
                "SELECT config_json FROM knowledge_bases WHERE kb_id=?",
                (kb_id,),
            ).fetchone()
        if row is None or row["config_json"] is None:
            return {}
        raw = str(row["config_json"])
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = {}
        return parsed if isinstance(parsed, dict) else {}

    def set_kb_config(self, *, kb_id: str, config: dict[str, Any]) -> None:
        '''设置知识库的JSON配置(config_json字段)'''
        with self._connection() as conn:
            conn.execute(
                "UPDATE knowledge_bases SET config_json=?, updated_at=? WHERE kb_id=?",
                (json.dumps(config, ensure_ascii=False), _now_iso(), kb_id),
            )

    def resolve_kb_config(self, *, kb_id: str, defaults: dict[str, Any]) -> dict[str, Any]:
        existing = self.get_kb_config(kb_id=kb_id)
        merged = dict(defaults)
        merged.update(existing) # 已有配置覆盖默认配置
        if merged != existing:
            self.set_kb_config(kb_id=kb_id, config=merged) # 持久化合并结果
        return merged

    def list_knowledge_bases(self) -> list[dict[str, Any]]:
        '''查询当前已有的知识库以及其描述'''
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT kb_id, kb_name, description
                FROM knowledge_bases
                ORDER BY kb_name
                """
            ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            out.append(
                {
                    "kb_id": str(r["kb_id"]),
                    "kb_name": str(r["kb_name"]),
                    "description": str(r["description"])
                    if r["description"] is not None
                    else None,
                }
            )
        return out

    def delete_kb(self, *, kb_id: str) -> None:
        kb_id = str(kb_id or "").strip()
        if not kb_id:
            return
        with self._connection() as conn:
            rows = conn.execute("SELECT doc_id FROM documents WHERE kb_id=?", (kb_id,)).fetchall()
            doc_ids = [str(r["doc_id"]) for r in rows if r and r["doc_id"] is not None]
            if doc_ids:
                placeholders = ",".join("?" for _ in doc_ids)
                conn.execute(f"DELETE FROM chunks WHERE doc_id IN ({placeholders})", doc_ids)
                conn.execute(f"DELETE FROM summaries WHERE doc_id IN ({placeholders})", doc_ids)
                conn.execute(f"DELETE FROM subq_mapping WHERE doc_id IN ({placeholders})", doc_ids)
                conn.execute(f"DELETE FROM documents WHERE doc_id IN ({placeholders})", doc_ids)
            conn.execute("DELETE FROM ingest_runs WHERE kb_id=?", (kb_id,))
            conn.execute("DELETE FROM knowledge_bases WHERE kb_id=?", (kb_id,))

    def start_ingest_run(self, *, kb_id: str, request_id: str | None = None) -> str:
        '''开始导入任务
        1. 记录一次文档导入的开始，状态设为 running
        2. 返回ingest_id
        '''
        ingest_id = new_id() # 生成唯一UUID
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO ingest_runs (ingest_id, kb_id, request_id, status, error_message, started_at, finished_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (ingest_id, kb_id, request_id, "running", None, _now_iso(), None),
            )
        return ingest_id

    def finish_ingest_run(
        self, *, ingest_id: str, status: str, error_message: str | None = None
    ) -> None:
        '''完成导入任务
        1. 更新导入任务状态（success 或 failed），记录结束时间
        '''
        with self._connection() as conn:
            conn.execute(
                """
                UPDATE ingest_runs
                SET status=?, error_message=?, finished_at=?
                WHERE ingest_id=?
                """,
                (status, error_message, _now_iso(), ingest_id),
            )

    def upsert_document(
        self,
        *,
        kb_id: str, # 知识库id
        doc_text: str, # 文档原文
        metadata: DocumentMetadata, # 文档元数据对象
        default_source: str, # 默认来源（如果metadata没有提供）
    ) -> tuple[str, str]:
        '''插入或更新文档
        1. 返回确定的文档ID和内容哈希
        '''
        content_hash = sha256_text(doc_text) # 内容hash
        doc_id = metadata.doc_id or new_id() # 文档id：优先使用提供的，否则生成
        source = metadata.source or default_source # 文档来源：优先使用提供的，否则用默认
        with self._connection() as conn: # 执行插入/更新
            conn.execute(
                """
                INSERT INTO documents (
                  doc_id, kb_id, source, title, author, created_date, ingested_at,
                  content_hash, tags_json, custom_fields_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(kb_id, source) DO UPDATE SET
                  title=excluded.title,
                  author=excluded.author,
                  created_date=excluded.created_date,
                  ingested_at=excluded.ingested_at,
                  content_hash=excluded.content_hash,
                  tags_json=excluded.tags_json,
                  custom_fields_json=excluded.custom_fields_json
                """,
                (
                    doc_id,
                    kb_id,
                    source,
                    metadata.title,
                    metadata.author,
                    metadata.created_date,
                    _now_iso(),
                    content_hash,
                    json.dumps(metadata.tags, ensure_ascii=False),
                    json.dumps(metadata.custom_fields, ensure_ascii=False),
                ),
            )
            row = conn.execute( # 查询实际的文档ID
                "SELECT doc_id FROM documents WHERE kb_id=? AND source=?", (kb_id, source)
            ).fetchone()
            resolved_doc_id = str(row["doc_id"]) if row else doc_id
        return resolved_doc_id, content_hash

    def get_document_by_source(self, *, kb_id: str, source: str) -> dict[str, Any] | None:
        '''通过source获取文档'''
        with self._connection() as conn:
            row = conn.execute(
                "SELECT doc_id, content_hash FROM documents WHERE kb_id=? AND source=?",
                (kb_id, source),
            ).fetchone()
        if row is None:
            return None
        return {"doc_id": str(row["doc_id"]), "content_hash": str(row["content_hash"])}

    def get_chunk_ids_by_doc(self, *, doc_id: str) -> dict[int, str]:
        '''获取文档的chunk_id'''
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT chunk_index, chunk_id FROM chunks WHERE is_active=1 AND doc_id=? ORDER BY chunk_index",
                (doc_id,),
            ).fetchall()
        out: dict[int, str] = {}
        for r in rows:
            out[int(r["chunk_index"])] = str(r["chunk_id"])
        return out

    def deactivate_chunks_by_doc(self, *, doc_id: str) -> None:
        '''把这篇文档现存的 chunks 全部 is_active=0'''
        with self._connection() as conn:
            conn.execute("UPDATE chunks SET is_active=0 WHERE doc_id=?", (doc_id,))

    def filter_chunk_ids(
        self, *, chunk_ids: list[str], filters: dict[str, Any] | None
    ) -> tuple[list[str], dict[str, dict[str, Any]]]:
        '''过滤chunk ID列表，基于元数据条件
        Args:
            chunk_ids：待过滤的chunk ID列表
            filters：过滤条件字典 (如{"author": "张三", "source": "custom://a"})
        Returns:
            元组 (过滤后的ID列表, chunk元数据字典)
        '''
        if not chunk_ids:
            return [], {}
        if filters is None:
            filters = {}

        author = filters.get("author") # 提取过滤条件
        source = filters.get("source")
        created_date = filters.get("created_date")
        doc_id_filter = filters.get("doc_id")

        placeholders = ",".join("?" for _ in chunk_ids)
        params: list[Any] = list(chunk_ids)
        # 构建过滤SQL
        sql = f"""
        SELECT
          c.chunk_id AS chunk_id,
          c.doc_id AS doc_id,
          d.source AS source,
          d.author AS author,
          d.created_date AS created_date
        FROM chunks c
        JOIN documents d ON d.doc_id = c.doc_id
        WHERE c.is_active = 1 AND c.chunk_id IN ({placeholders})
        """

        if doc_id_filter is not None:
            sql += " AND c.doc_id = ?"
            params.append(doc_id_filter)
        if author is not None:
            sql += " AND d.author = ?"
            params.append(author)
        if source is not None:
            sql += " AND d.source = ?"
            params.append(source)
        if created_date is not None:
            sql += " AND d.created_date = ?"
            params.append(created_date)

        with self._connection() as conn:
            rows = conn.execute(sql, params).fetchall()

        allowed: set[str] = set() # 过滤后的chunk ID集合
        meta_by_chunk: dict[str, dict[str, Any]] = {} # 每个chunk的元数据字典
        for r in rows:
            cid = str(r["chunk_id"])
            allowed.add(cid)
            meta_by_chunk[cid] = {
                "doc_id": str(r["doc_id"]),
                "source": str(r["source"]) if r["source"] is not None else None,
                "author": str(r["author"]) if r["author"] is not None else None,
                "created_date": str(r["created_date"])
                if r["created_date"] is not None
                else None,
            }

        ordered_allowed = [cid for cid in chunk_ids if cid in allowed] # 保持原始chunk_ids的顺序，只保留允许的ID
        return ordered_allowed, meta_by_chunk

    def upsert_chunk(
        self,
        *,
        doc_id: str,
        chunk_id: str,
        chunk_index: int, # 在文档中的序号
        content_hash: str,
        text_ref: str | None, # 对象存储路径: 指向对象存储中的实际文本
        token_count: int | None = None,
        start_offset: int | None = None,
        end_offset: int | None = None,
    ) -> None:
        '''插入或更新分块'''
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO chunks (
                  chunk_id, doc_id, chunk_index, text_ref, content_hash, is_active,
                  token_count, start_offset, end_offset, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(doc_id, chunk_index) DO UPDATE SET
                  text_ref=excluded.text_ref,
                  content_hash=excluded.content_hash,
                  is_active=excluded.is_active,
                  token_count=excluded.token_count,
                  start_offset=excluded.start_offset,
                  end_offset=excluded.end_offset
                """,
                (
                    chunk_id,
                    doc_id,
                    chunk_index,
                    text_ref,
                    content_hash,
                    1,
                    token_count,
                    start_offset,
                    end_offset,
                    _now_iso(),
                ),
            )

    def get_chunk_refs(self, *, chunk_ids: list[str]) -> dict[str, dict[str, Any]]:
        '''批量获取 chunk 引用
        1. 根据 chunk ID 列表，批量查询它们的位置信息（用于检索时定位原文）
        '''
        if not chunk_ids:
            return {}
        # 构建参数化查询（防止SQL注入）
        placeholders = ",".join("?" for _ in chunk_ids)
        with self._connection() as conn:
            rows = conn.execute(
                f"SELECT chunk_id, doc_id, chunk_index, text_ref FROM chunks WHERE is_active=1 AND chunk_id IN ({placeholders})",
                chunk_ids,
            ).fetchall()
        # 转换为字典：{chunk_id: {doc_id, chunk_index, text_ref}}
        out: dict[str, dict[str, Any]] = {}
        for r in rows:
            out[str(r["chunk_id"])] = {
                "doc_id": str(r["doc_id"]),
                "chunk_index": int(r["chunk_index"]),
                "text_ref": str(r["text_ref"]) if r["text_ref"] is not None else None,
            }
        return out

    def upsert_summary(
        self,
        *,
        summary_id: str,
        doc_id: str,
        text_ref: str,
        chunk_ids: list[dict[str, Any]] | list[str],
        content_hash: str,
    ) -> None:
        '''插入或更新摘要
        1. 存储或更新文档的摘要信息，记录摘要与 chunk 的关联关系
        '''
        chunk_ids_json = json.dumps(chunk_ids, ensure_ascii=False)
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO summaries (
                  summary_id, doc_id, text_ref, chunk_ids_json, content_hash, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(summary_id) DO UPDATE SET
                  doc_id=excluded.doc_id,
                  text_ref=excluded.text_ref,
                  chunk_ids_json=excluded.chunk_ids_json,
                  content_hash=excluded.content_hash
                """,
                (summary_id, doc_id, text_ref, chunk_ids_json, content_hash, _now_iso()),
            )

    def get_summary_chunk_ids(self, *, summary_ids: list[str]) -> dict[str, list[str]]:
        '''获取摘要关联的 chunk ID
        1. 根据摘要 ID 列表，批量查询每个摘要关联的 chunk ID 列表
        '''
        if not summary_ids:
            return {}
        placeholders = ",".join("?" for _ in summary_ids) # 批量查询摘要的 JSON 字段
        with self._connection() as conn:
            rows = conn.execute(
                f"SELECT summary_id, chunk_ids_json FROM summaries WHERE summary_id IN ({placeholders})",
                summary_ids,
            ).fetchall()

        out: dict[str, list[str]] = {} # 解析 JSON 并提取 chunk ID
        for r in rows:
            raw = str(r["chunk_ids_json"]) if r["chunk_ids_json"] is not None else "[]"
            try:
                parsed = json.loads(raw)
            except Exception:
                parsed = []

            chunk_list: list[str] = []
            if isinstance(parsed, list):
                for item in parsed:
                    if isinstance(item, str):
                        chunk_list.append(item)
                    elif isinstance(item, dict) and "chunk_id" in item:
                        chunk_list.append(str(item["chunk_id"]))
            out[str(r["summary_id"])] = chunk_list
        return out

    def upsert_subq_mapping(
        self,
        *,
        question_id: str,
        doc_id: str,
        chunk_id: str,
        question_text: str,
        content_hash: str,
    ) -> None:
        '''插入或更新子问题映射
        1. 记录子问题（sub-question）与 chunk 的映射关系，用于复杂查询的分解
        '''
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO subq_mapping (
                  question_id, doc_id, chunk_id, question_text, content_hash, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(question_id) DO UPDATE SET
                  doc_id=excluded.doc_id,
                  chunk_id=excluded.chunk_id,
                  question_text=excluded.question_text,
                  content_hash=excluded.content_hash
                """,
                (question_id, doc_id, chunk_id, question_text, content_hash, _now_iso()),
            )

    def get_subq_chunk_ids(self, *, question_ids: list[str]) -> dict[str, str]:
        '''获取子问题映射
        1. 根据子问题 ID 列表，批量查询每个子问题对应的 chunk ID
        '''
        if not question_ids:
            return {}
        placeholders = ",".join("?" for _ in question_ids)
        with self._connection() as conn:
            rows = conn.execute(
                f"SELECT question_id, chunk_id FROM subq_mapping WHERE question_id IN ({placeholders})",
                question_ids,
            ).fetchall()

        out: dict[str, str] = {}
        for r in rows:
            qid = str(r["question_id"])
            cid = str(r["chunk_id"])
            out[qid] = cid
        return out

    def count_summaries_by_doc(self, *, doc_id: str) -> int:
        '''统计文档的摘要数量'''
        with self._connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM summaries WHERE doc_id=?",
                (doc_id,),
            ).fetchone()
        return int(row["cnt"]) if row else 0

    def count_subq_by_doc(self, *, doc_id: str) -> int:
        '''统计文档的子问题数量'''
        with self._connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM subq_mapping WHERE doc_id=?",
                (doc_id,),
            ).fetchone()
        return int(row["cnt"]) if row else 0
