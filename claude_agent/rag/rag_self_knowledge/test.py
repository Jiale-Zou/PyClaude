import sys
from pathlib import Path
_src_root = Path(__file__).resolve().parents[1]
if str(_src_root) not in sys.path:
    sys.path.insert(0, str(_src_root))

from rag_self_knowledge import add_documents, search_knowledge
from rag_self_knowledge.config.settings import Settings
from rag_self_knowledge.models.document import DocumentMetadata

settings = Settings(
    enable_summary_index=True,
    enable_subq_index=True,
)

docs = [
    "作者张三。主题：RRF 融合。score(d)=Σ 1/(k+rank)。用于多路召回融合。",
    "作者李四。主题：SQLite。要避免文件锁，务必关闭连接，减少长事务。",
]
metas = [
    DocumentMetadata(source="custom://doc1", author="张三", created_date="2026-05-12", tags=["retrieval"]),
    DocumentMetadata(source="custom://doc2", author="李四", created_date="2026-05-12", tags=["sqlite"]),
]

add_documents("kb_demo", docs, metas, settings=settings)

results = search_knowledge("kb_demo", "多路召回融合怎么做？", top_k=3, settings=settings)
print(len(results), results[0].metadata.get("author"), results[0].text[:50])

filtered = search_knowledge("kb_demo", "SQLite", top_k=3, settings=settings, filters={"author": "李四"})
print(len(filtered), [r.metadata.get("author") for r in filtered])