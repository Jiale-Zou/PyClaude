from __future__ import annotations

'''
knowledge_bases - 知识库管理：支持多个知识库
documents - 文档管理：记录文档来源、哈希、元数据
chunks - 分块管理：记录 chunk 的位置和引用
summaries - 摘要管理（预留表）
subq_mapping - 子查询映射（预留表）
ingest_runs - 导入任务追踪：记录文档处理状态
'''


SQLITE_DDL = """
CREATE TABLE IF NOT EXISTS knowledge_bases (
  kb_id            TEXT PRIMARY KEY,
  kb_name          TEXT NOT NULL UNIQUE,
  description      TEXT,
  config_json      TEXT NOT NULL DEFAULT '{}',
  created_at       TEXT NOT NULL,
  updated_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
  doc_id           TEXT PRIMARY KEY,
  kb_id            TEXT NOT NULL,
  source           TEXT NOT NULL,
  title            TEXT,
  author           TEXT,
  created_date     TEXT,
  ingested_at      TEXT NOT NULL,
  content_hash     TEXT NOT NULL,
  tags_json        TEXT NOT NULL DEFAULT '[]',
  custom_fields_json TEXT NOT NULL DEFAULT '{}',
  UNIQUE(kb_id, source)
);

CREATE TABLE IF NOT EXISTS chunks (
  chunk_id         TEXT PRIMARY KEY,
  doc_id           TEXT NOT NULL,
  chunk_index      INTEGER NOT NULL,
  text_ref         TEXT,
  content_hash     TEXT NOT NULL,
  is_active        INTEGER NOT NULL DEFAULT 1,
  token_count      INTEGER,
  start_offset     INTEGER,
  end_offset       INTEGER,
  created_at       TEXT NOT NULL,
  UNIQUE(doc_id, chunk_index)
);

CREATE TABLE IF NOT EXISTS summaries (
  summary_id       TEXT PRIMARY KEY,
  doc_id           TEXT NOT NULL,
  text_ref         TEXT NOT NULL,
  chunk_ids_json   TEXT NOT NULL,
  content_hash     TEXT NOT NULL,
  created_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS subq_mapping (
  question_id      TEXT PRIMARY KEY,
  doc_id           TEXT NOT NULL,
  chunk_id         TEXT NOT NULL,
  question_text    TEXT NOT NULL,
  content_hash     TEXT NOT NULL,
  created_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ingest_runs (
  ingest_id        TEXT PRIMARY KEY,
  kb_id            TEXT NOT NULL,
  request_id       TEXT,
  status           TEXT NOT NULL,
  error_message    TEXT,
  started_at       TEXT NOT NULL,
  finished_at      TEXT
);
"""
