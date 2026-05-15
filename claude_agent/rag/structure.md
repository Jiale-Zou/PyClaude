搭建一个个人知识库RAG系统，将功能接口暴露为函数。

# 一、整体架构分层
┌─────────────────────────────────────────────────┐
│                        调用层                    │
│  - 函数接口: search_knowledge(), add_documents() │
└─────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────┐
│                编排层 (Orchestrator)             │
│  - 流程编排、多路召回协调、结果融合                  │
└─────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────┐
│                核心模块层                         │
│  ├── 文档分割模块                                 │
│  ├── 索引构建模块                                 │
│  ├── 召回模块                                    │
│  └── 元数据管理模块                               │
└─────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────┐
│                存储层                            │
│  - 向量数据库 (Chroma/Qdrant/Milvus)              │
│  - 关系数据库 (SQLite/PostgreSQL) 存元数据/映射     │
│  - 对象存储 (文件系统/MinIO) 存原始块               │
└─────────────────────────────────────────────────┘

# 二、模块详细设计
## 1. 文档分割模块(Chunker)
类结构：
- BaseChunker (抽象基类)
    - chunk(text, metadata) → List[Chunk]
- FixedSizeChunker (固定大小切分)
    - 参数: chunk_size (64/128/256), overlap, unit('char'/'token')
    - 使用 tiktoken 计算 token 数
- PunctuationChunker (标点符号切分)
    - 参数: chunk_size, sentence_splitter(使用nltk/re)
    - 贪心策略: 累积句子直到超过chunk_size
- SemanticChunker (语义切分)
    - 参数: threshold, sentence_model(Bert模型)
    - 实现: 句子embedding → 计算相邻相似度 → 相似度低于阈值时切分
依赖：
- token计算: tiktoken
- 句子切分: nltk.tokenize 或 re
- 语义模型: sentence-transformers

## 2. 索引模块(Indexer)
三层索引结构：
1. 直接索引 (DirectIndexer)
    - 存储: Chunk原文 + embedding
    - 映射: chunk_id → 原始内容
2. 摘要索引 (SummaryIndexer)
    - 工作流: 大块文本(如原始chunk_size的5-10倍) → LLM生成摘要(200token) → 摘要存入向量库 → 建立 summary_id → original_chunk_ids 映射
3. 子问题索引 (SubQuestionIndexer)
    - 工作流: Chunk文本 → LLM生成N个可能被问到的问题(3-5个) → 问题向量化存储 → 建立 question_id → chunk_id 映射
存储设计：
- 向量库collection命名规范：{kb_name}_direct、{kb_name}_summary、{kb_name}_subq。
- 映射表(关系DB)：summary_mapping (summary_id, chunk_ids JSON)、subq_mapping (question_id, chunk_id)

## 3. 元数据管理模块(MetadataManager)
数据结构（文档·1元数据）：
```
DocumentMetadata = {
    "doc_id": str,
    "source": str,          # 文件路径/URL
    "author": str,
    "created_date": str,
    "tags": List[str],
    "custom_fields": dict   # 用户自定义KV
}
```
功能：
- 元数据Schema验证(使用Pydantic)
- 过滤查询: 支持等值、范围、IN、正则等条件

## 4. 召回模块 (Retriever)
多路召回流程：
```
用户问题 → QueryProcessor(改写+拆解)
                ↓
        ┌───────┴───────┐
        ↓               ↓
   直接召回        摘要召回        子问题召回
   (embedding)    (embedding)    (embedding)
        ↓               ↓               ↓
     topK_d        topK_s          topK_q
        └───────┬───────┘
                ↓
            RRF融合
                ↓
         Metadata过滤
                ↓
          重排序(Rerank)
                ↓
           去重合并
                ↓
           最终结果
```
子模块：
### QueryProcessor
- 问题改写: LLM润色/扩写问题
- 问题拆解: LLM将复杂问题拆为子问题列表
- 输出: List[SubQuery]
### MultiPathRetriever
- 配置各路的权重和topK
- 调用向量库相似度搜索(余弦距离)
- 返回各路的 List[RetrievalResult]
### RRF融合器 (Reciprocal Rank Fusion)
```
公式: score(d) = Σ 1/(k + rank_i(d))
k=60(经验值)
```
实现: 收集所有召回结果的排名 → 计算融合分数
### MetadataFilter
- 解析过滤条件(如: "author='张三' AND tags包含'AI'")
- 转为SQL/向量库filter条件
- 应用过滤
### Reranker
- 使用交叉编码器(如 cross-encoder/ms-marco-MiniLM-L-6-v2)
- 对(问题, chunk内容)计算相关性分数
- 重排序
### 结果组装器
- 去重(按chunk_id)
- 多样性策略: 按来源文档交替排列
- 输出格式: [(chunk, score, metadata), ...]

# 三、核心联动流程
## 流程1: 文档入库
```
用户调用 add_documents(kb_name, docs, metadatas)
         ↓
1. 获取知识库配置(索引类型启用开关)
         ↓
2. 对每个文档:
   ├─ 文档分割(选择chunker)
   ├─ 生成chunk_id, 绑定metadata
   └─ 并发处理:
        ├─ 直接索引: 直接embedding + 存入向量库
        ├─ 摘要索引(如启用): 
        │   chunk聚合 → LLM摘要 → embedding → 存摘要库
        └─ 子问题索引(如启用):
            LLM生成问题 → embedding → 存问题库 + 映射表
         ↓
3. 提交事务(向量库+关系库同时成功)
```
并发设计：
    - 使用线程池处理文档(LLM调用较多)
    - 批量embedding提交(减少网络IO)
## 流程2: 召回查询
```
用户调用 search_knowledge(kb_name, query, filters=None, topK=5)
         ↓
1. QueryProcessor处理问题
   ├─ 可选: LLM改写(增强表达)
   └─ 可选: 问题拆解(多子问题)
         ↓
2. 对每个子问题:
   ├─ 并行多路召回(直接/摘要/子问题)
   │   └─ 向量库检索: 相似度阈值0.7, 每路取topK*2
   ├─ 收集结果 → 按RRF融合
   └─ 应用metadata过滤
         ↓
3. 汇总所有子问题结果
   ├─ 去重保留最高分
   └─ Reranker精排
         ↓
4. 结果后处理
   ├─ 质量过滤(分数阈值)
   ├─ 多样性采样
   └─ 组装为最终格式
         ↓
5. 返回 List[Result]
```


---

# 四. 目录树
## 1. 目录树
```text
rag_self_knowledge/
  pyproject.toml
  README.md
  .env.example
  .gitignore

  src/
    rag_self_knowledge/
      __init__.py
      api.py

      orchestrator/
        __init__.py
        ingest_orchestrator.py
        query_orchestrator.py
        rrf.py
        retry.py

      core/
        __init__.py

        chunking/
          __init__.py
          base.py
          fixed_size.py
          punctuation.py
          semantic.py

        indexing/
          __init__.py
          direct.py
          summary.py
          subquestion.py

        retrieval/
          __init__.py
          query_processor.py
          multipath.py
          metadata_filter.py
          reranker.py
          postprocess.py

        metadata/
          __init__.py
          schema.py
          manager.py
          validators.py

      storage/
        __init__.py

        vector/
          __init__.py
          base.py
          chroma.py
          qdrant.py
          milvus.py

        relational/
          __init__.py
          base.py
          postgres.py
          sqlite.py
          ddl.py

        object_store/
          __init__.py
          base.py
          filesystem.py
          minio.py

      models/
        __init__.py
        ids.py
        document.py
        chunk.py
        retrieval.py

      utils/
        __init__.py
        hashing.py
        time.py
        text.py
        concurrency.py

      config/
        __init__.py
        settings.py
        kb_config.py

  db/
    migrations/
      001_init.sql
    seeds/
      knowledge_bases.sql

  scripts/
    ingest.py
    query.py
    create_kb.py

  tests/
    test_chunkers.py
    test_rrf.py
    test_metadata_filter.py

  blobs/
    {kb_name}/
      documents/
        {doc_id}/
          raw
      chunks/
        {doc_id}/
          {chunk_id}.txt
      summaries/
        {doc_id}/
          {summary_id}.txt
```

说明：
- `src/`：推荐使用 src-layout，避免本地导入路径与打包后行为不一致。
- `blobs/`：对象存储在文件系统模式下的落盘根目录；若切到 MinIO/S3，该目录对应 bucket 中的 `blobs/` 前缀。

---

## 2. 与分层设计的对应关系

### 2.1 调用层（函数接口）
- `src/rag_self_knowledge/api.py`
  - `add_documents(kb_name, docs, metadatas, ...)`
  - `search_knowledge(kb_name, query, filters=None, topK=5, ...)`
- `src/rag_self_knowledge/__init__.py`
  - 只 re-export 对外 API，保持入口稳定，内部可重构。

### 2.2 编排层（Orchestrator）
- `src/rag_self_knowledge/orchestrator/ingest_orchestrator.py`
  - 负责入库全流程：切分→写关系库→向量 upsert→对象存储→更新 ingest_runs
- `src/rag_self_knowledge/orchestrator/query_orchestrator.py`
  - 负责查询全流程：QueryProcessor→多路召回→RRF→过滤→精排→去重合并
- `src/rag_self_knowledge/orchestrator/rrf.py`
  - RRF 融合器（与 structure.md 里的公式一致）
- `src/rag_self_knowledge/orchestrator/retry.py`
  - “入库流水 + 幂等键 + 可重试”的统一策略封装（对齐 table.md 的 ingest_runs）

### 2.3 核心模块层（Chunker / Indexer / Retriever / Metadata）
- Chunker：`src/rag_self_knowledge/core/chunking/`
  - `base.py` 定义抽象接口与 Chunk 数据结构要求
  - `fixed_size.py / punctuation.py / semantic.py` 提供具体策略
- Indexer：`src/rag_self_knowledge/core/indexing/`
  - `direct.py` 写 `{kb_name}_direct`
  - `summary.py` 写 `{kb_name}_summary` + `summaries`
  - `subquestion.py` 写 `{kb_name}_subq` + `subq_mapping`
- Retriever：`src/rag_self_knowledge/core/retrieval/`
  - `query_processor.py`（可选改写/拆解）
  - `multipath.py`（直接/摘要/子问题三路召回）
  - `metadata_filter.py`（SQL 精确过滤）
  - `reranker.py`（交叉编码器精排：可选）
  - `postprocess.py`（去重、多样性采样、阈值过滤、结果组装）
- Metadata：`src/rag_self_knowledge/core/metadata/`
  - `schema.py`（DocumentMetadata / ChunkMetadata 等 schema）
  - `manager.py`（过滤表达式解析、SQL 转换、校验与查询）

---

## 3. 存储层设计（与 table.md 对齐）

### 3.1 向量库（Collections）
放在 `src/rag_self_knowledge/storage/vector/`：
- `base.py`：统一接口（create_collection / upsert / query / delete / filter support）
- `chroma.py / qdrant.py / milvus.py`：按后端实现适配

Collections 命名遵循 table.md：
- `{kb_name}_direct`
- `{kb_name}_summary`
- `{kb_name}_subq`

建议在向量库 metadata 中仅放“高频、低基数、强约束”字段（doc_id/source/author/created_date 等），复杂过滤走 SQL（见 table.md 的 6.2）。

### 3.2 关系库（PostgreSQL/SQLite）
放在 `src/rag_self_knowledge/storage/relational/`：
- `ddl.py`：把 table.md 的 DDL 以代码或模板方式组织（便于初始化/迁移）
- `postgres.py / sqlite.py`：分别封装连接、事务、幂等 upsert、查询

与 table.md 的核心表对应：
- `knowledge_bases`：知识库配置与开关（chunk/召回/索引参数）
- `documents`：文档元数据 + `content_hash` 幂等
- `chunks`：chunk 可追溯信息（`chunk_index/content_hash/text_ref`）
- `summaries`：摘要实体（可选）
- `subq_mapping`：question_id → chunk_id
- `ingest_runs`：入库流水（最终一致与可重试）

SQL 文件建议集中放在：
- `db/migrations/001_init.sql`：初始建表（直接来自 table.md 的 PostgreSQL DDL 部分）

### 3.3 对象存储（文件系统 / MinIO）
放在 `src/rag_self_knowledge/storage/object_store/`：
- `filesystem.py`：本地落盘（对应 `blobs/` 目录）
- `minio.py`：S3 兼容对象存储

`text_ref` 统一格式（table.md 的 5.2）：
- 文件系统：`fs://d:/.../blobs/...`
- MinIO/S3：`s3://bucket/blobs/...`

---

## 4. 数据模型与类型

推荐将跨层共享的数据结构集中在 `src/rag_self_knowledge/models/`，避免循环依赖：
- `document.py`：Document / DocumentMetadata
- `chunk.py`：Chunk / ChunkMetadata（包含 doc_id/chunk_index/text_ref/content_hash 等）
- `retrieval.py`：RetrievalResult / SearchResult（面向返回值）
- `ids.py`：ID 生成策略（UUIDv7/ULID 的选择与统一封装）

---

## 5. 配置组织方式

`src/rag_self_knowledge/config/`：
- `settings.py`：环境级配置（DB URL、向量库地址、对象存储配置、并发度等）
- `kb_config.py`：知识库级配置（chunker/indexer/retriever 开关与参数），建议落在关系库的 `knowledge_bases.config`（table.md 3.1）

---

## 6. 脚本与测试

为“函数接口 + 可复现”的开发体验，推荐保留：
- `scripts/ingest.py`：命令行调用 add_documents 的薄封装（便于调试与回归）
- `scripts/query.py`：命令行调用 search_knowledge 的薄封装
- `tests/`：对 chunker、RRF、过滤器等纯逻辑模块做单测；对存储适配层做最小集成测试（可选）