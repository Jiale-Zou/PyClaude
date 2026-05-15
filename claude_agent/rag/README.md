# rag_self_knowledge（个人知识库 RAG）

基于函数接口的个人知识库 RAG 原型，实现“文档入库 → 向量检索 → SQL 过滤 → 后处理 → 返回可追溯结果”的闭环，并支持可选的摘要索引与子问题索引。

相关设计文档：
- 架构分层：[structure.md](file:///./structure.md)
- 存储与表结构：[table.md](file:///./table.md)

---

## 目录结构

```
rag/
  README.md
  pyproject.toml
  structure.md
  table.md

  models--embaas--sentence-transformers-e5-large-v2/ # Embedding模型

  rag_self_knowledge/
    api.py # 函数暴露
    test.py # 测试脚本

    config/ # 配置项
      settings.py

    core/
      chunking/ # 切块模块
        base.py
        fixed_size.py

    models/ # 数据模型模块
      chunk.py
      document.py
      ids.py
      retrieval.py

    orchestrator/
      ingest_orchestrator.py # 文档入库编排器
      query_orchestrator.py # RAG查询编排器
      rrf.py

    storage/
      object_store/ # 对象存储
        base.py
        filesystem.py

      relational/ # 关系映射存储
        ddl.py
        sqlite.py

      vector/ # 向量存储
        base.py
        chromadb.py
        inmemory.py

    utils/ # 工具模块
      hashing.py # 哈希化
      ollama.py # ollama接口
      text.py

  storage_data/ # 存储目录
      object_data/
      relational_data/
      vector_data/
```

---

## 快速开始（Windows / PowerShell）

### 1) 安装依赖

项目支持“无外部服务”的最小闭环；如果希望向量库跨进程持久化，建议安装 Chroma：

```powershell
pip install chromadb
```

如果你要启用 `SentenceTransformerEmbedder`，再安装：

```powershell
pip install sentence-transformers
```

使用的模型为[embed](file:///./models--embaas--sentence-transformers-e5-large-v2)

### 1) 安装依赖

测试脚本

```
python test.py
```

---

## 配置说明

### Settings（进程级默认值）

见：[settings.py](file:///./rag_self_knowledge/config/settings.py)

常用字段：
- `sqlite_path`：SQLite 文件路径
- `blobs_root`：对象存储根目录
- `vector_root`：Chroma 持久化目录
- `enable_summary_index / enable_subq_index`：是否启用摘要/子问题索引
- `summary_group_size / summary_max_chars / subq_per_chunk`：摘要与子问题生成参数
- `min_score`：后处理阈值过滤
- `enable_diversity / diversity_key`：多样性开关与分桶 key（默认 doc_id）

### KB 配置（knowledge_bases.config_json，持久化）

运行时会将 Settings 的默认值写入/合并到 `knowledge_bases.config_json`，实现“同一进程/同一数据库中，不同 kb 可有不同配置”：
- 读取/合并逻辑：[sqlite.py](file:///./rag_self_knowledge/storage/relational/sqlite.py)
- ingest/search 会自动调用 resolve

---

## 外部暴露
见：[api.py](file:///./rag_self_knowledge/api.py)
- add_documents: 将一批文档写入指定知识库（入库流程）
- search_knowledge: 在指定知识库中检索与 query 相关的内容（查询流程）。
- list_knowledge_bases: 查询当前已存在的知识库列表及其描述信息。
