# 数据存储方案（RAG个人知识库）

本方案按 `structure.md` 的分层设计，对应三类存储：
- 向量库：存 embedding + 轻量元数据，用于相似度检索与初筛
- 关系库（推荐 PostgreSQL；也可 SQLite）：存强一致的元数据、映射关系、入库流水
- 对象存储（文件系统/MinIO）：存原始文档与分块正文（可选，但建议用于可追溯与降成本）

---

## 1. 向量库（Collections 设计）

Collection 命名规范（与 `structure.md` 一致）：
- `{kb_name}_direct`
- `{kb_name}_summary`
- `{kb_name}_subq`

### 1.1 `{kb_name}_direct`（DirectIndexer）
- id：`chunk_id`（UUID/ULID 字符串）
- document：`chunk_text`（可存原文；如向量库有长度限制则仅存摘要/截断）
- embedding：`chunk_embedding`
- metadata（建议字段，便于向量库侧过滤/召回后聚合）：
  - `kb_name`：知识库名
  - `doc_id`
  - `chunk_index`：块序号（int）
  - `source`：文件路径/URL
  - `author`
  - `created_date`（ISO8601 字符串）
  - `tags`：数组/逗号串（按向量库能力选择）
  - `content_hash`：用于幂等去重
  - `text_ref`：对象存储引用（可选）

### 1.2 `{kb_name}_summary`（SummaryIndexer）
- id：`summary_id`
- document：`summary_text`
- embedding：`summary_embedding`
- metadata：
  - `kb_name`
  - `doc_id`
  - `chunk_ids`：数组/JSON 字符串（或只存 `summary_id`，映射完全放关系库）
  - `content_hash`

### 1.3 `{kb_name}_subq`（SubQuestionIndexer）
- id：`question_id`
- document：`question_text`
- embedding：`question_embedding`
- metadata：
  - `kb_name`
  - `doc_id`
  - `chunk_id`
  - `content_hash`

---

## 2. 关系库（表设计）

### 2.1 设计目标
- 元数据强一致：`doc_id / chunk_id / summary_id / question_id` 等 ID 与映射可追溯
- 支持过滤：等值/范围/IN/正则（其中正则在 SQL 层实现更可靠）
- 支持幂等：同一文档重复入库可检测、可增量更新
- 支持入库事务：向量库与关系库跨存储无法原子提交，因此用“入库流水 + 幂等键 + 可重试”实现最终一致

### 2.2 核心实体关系（简化）
- knowledge_bases 1—N documents
- documents 1—N chunks
- summaries N—M chunks（通过 summary_mapping）
- subquestions N—1 chunks（通过 subq_mapping）

---

## 3. PostgreSQL DDL（推荐）

### 3.1 knowledge_bases（知识库配置）

```sql
CREATE TABLE knowledge_bases (
  kb_id            TEXT PRIMARY KEY,
  kb_name          TEXT NOT NULL UNIQUE,
  description      TEXT,
  config           JSONB NOT NULL DEFAULT '{}'::jsonb,  -- 存chunk/召回/索引配置
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### 3.2 documents（文档元数据）

```sql
CREATE TABLE documents (
  doc_id           TEXT PRIMARY KEY,
  kb_id            TEXT NOT NULL REFERENCES knowledge_bases(kb_id) ON DELETE CASCADE,
  source           TEXT NOT NULL,  -- 唯一标识：file:///path 或 custom://id
  title           TEXT,
  author          TEXT,
  created_date    TEXT,  -- 用户自定义日期字符串
  ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  content_hash    TEXT NOT NULL,
  custom_fields   JSONB NOT NULL DEFAULT '{}'::jsonb,
  
  UNIQUE(kb_id, source)  -- 直接用组合唯一约束
);

-- 索引优化
CREATE INDEX idx_docs_kb_id ON documents(kb_id);
CREATE INDEX idx_docs_content_hash ON documents(content_hash);
CREATE INDEX idx_docs_custom_fields ON documents USING GIN (custom_fields);
```

### 3.3 document_tags（文档标签）

```sql
ALTER TABLE documents ADD COLUMN tags TEXT[];  -- PostgreSQL数组类型
CREATE INDEX idx_docs_tags ON documents USING GIN (tags);
```

### 3.4 chunks（分块索引与可追溯信息）

```sql
CREATE TABLE chunks (
  chunk_id         TEXT PRIMARY KEY,
  doc_id           TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
  chunk_index      INTEGER NOT NULL,
  text_ref         TEXT,  -- 对象存储路径
  content_hash     TEXT NOT NULL,
  token_count      INTEGER,
  start_offset     INTEGER,
  end_offset       INTEGER,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  
  UNIQUE(doc_id, chunk_index)
);

CREATE INDEX idx_chunks_doc_id ON chunks(doc_id);
CREATE INDEX idx_chunks_content_hash ON chunks(content_hash);
```

说明：
- `text_ref`：对象存储路径/URL（推荐），例如 `fs://...` / `s3://...`
- `preview_text`：用于调试与快速展示（可存前 N 字；避免大文本塞入 SQL）

### 3.5 summaries（摘要实体，选配）

如果希望对摘要做生命周期管理、回收与审计，建议保留摘要实体表：

```sql
-- 直接合并 summaries 和 summary_mapping，减少表数量
CREATE TABLE summaries (
  summary_id       TEXT PRIMARY KEY,
  doc_id           TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
  text_ref         TEXT NOT NULL,
  chunk_ids        JSONB NOT NULL,  -- 直接存 [{chunk_id, chunk_index}]
  content_hash     TEXT NOT NULL,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_summaries_doc_id ON summaries(doc_id);
CREATE INDEX idx_summaries_chunk_ids ON summaries USING GIN (chunk_ids);
```

### 3.7 subq_mapping（question_id → chunk_id）

```sql
CREATE TABLE subq_mapping (
  question_id      TEXT PRIMARY KEY,
  doc_id           TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
  chunk_id         TEXT NOT NULL REFERENCES chunks(chunk_id) ON DELETE CASCADE,
  question_text    TEXT NOT NULL,  -- 必需，便于调试和展示
  content_hash     TEXT NOT NULL,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX subq_mapping_doc_idx ON subq_mapping(doc_id);
CREATE INDEX subq_mapping_chunk_idx ON subq_mapping(chunk_id);
CREATE INDEX subq_mapping_content_hash_idx ON subq_mapping(content_hash);
```

### 3.8 ingest_runs（入库流水：实现最终一致与可重试）

```sql
CREATE TABLE ingest_runs (
  ingest_id        TEXT PRIMARY KEY,
  kb_id            TEXT NOT NULL REFERENCES knowledge_bases(kb_id) ON DELETE CASCADE,
  request_id       TEXT,
  status           TEXT NOT NULL,
  error_message    TEXT,
  started_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at      TIMESTAMPTZ
);

CREATE INDEX ingest_runs_kb_started_idx ON ingest_runs(kb_id, started_at);
CREATE INDEX ingest_runs_status_idx ON ingest_runs(status);
```

`status` 建议枚举值：`running | committed | failed | canceled`。

---

## 4. PostgreSQL 15+

---

## 5. 对象存储（文件系统/MinIO）目录结构

建议将原始文档与分块正文落盘/对象存储，向量库只保留检索所需的最小 text（或只保引用）。

### 5.1 路径规范
- 原始文档：
  - `blobs/{kb_name}/documents/{doc_id}/raw`
- 分块正文：
  - `blobs/{kb_name}/chunks/{doc_id}/{chunk_id}.txt`
- 摘要正文（如启用）：
  - `blobs/{kb_name}/summaries/{doc_id}/{summary_id}.txt`

### 5.2 text_ref 建议格式
- 文件系统：`fs://d:/.../blobs/...`
- MinIO/S3：`s3://bucket/blobs/...`

---

## 6. 过滤与查询落地建议

### 6.1 向量库侧（快速初筛）
- 仅放“高频、低基数、强约束”的字段到 metadata（如 `doc_id/source/author/created_date`）
- tags 如向量库不支持数组过滤，建议仅用于展示或做粗筛；精确过滤放 SQL 层

### 6.2 SQL 侧（精确过滤）
- author/source/created_date：直接走索引
- tags：通过 `document_tags` 做 `IN` 与组合条件
- custom_fields：PostgreSQL 使用 JSONB + GIN，支持灵活查询

---

## 7. ID 与幂等策略（强烈建议）

### 7.1 ID
- `doc_id/chunk_id/summary_id/question_id` 使用 UUIDv7 或 ULID（按时间有序，利于写入与索引）

### 7.2 content_hash
- 文档：对原始内容计算 hash（例如 SHA256），存 `documents.content_hash`
- chunk：对 chunk 文本计算 hash，存 `chunks.content_hash`
- summary/question：同理，作为 `content_hash` 用于去重与重试幂等

### 7.3 写入流程（与 `structure.md` 的“提交事务”对齐）
- 先写 `ingest_runs(status=running)`
- 落 `documents/chunks/mappings`（可先写或分阶段写，关键是保证可恢复）
- 向量库 upsert（以 id 幂等）
- 全部成功后 `ingest_runs(status=committed)`；失败则标记 `failed` 并保留错误信息便于重试
