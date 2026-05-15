from __future__ import annotations

"""
配置与依赖装配（Service Container）。

本模块的定位：
- 提供 Settings：集中管理运行期配置（路径、chunk 参数、embedding 维度等）
- 提供 RagServices：集中装配各类“可替换”依赖（关系库/向量库/对象存储/Chunker/Embedder）
- 提供 create_default_services：默认最小实现，保证项目在无外部服务时也能跑通闭环

与 table.md 的对应关系：
- relational：关系库（SQLite/PostgreSQL），存 documents/chunks/ingest_runs 等
- object_store：对象存储（FS/MinIO），存 chunk 正文，生成 text_ref
- vector：向量库（Chroma/Qdrant/Milvus），存 embedding + 轻量 metadata
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
import requests

try:
    from ..core.chunking.fixed_size import FixedSizeChunker
    from ..storage.object_store.filesystem import FileSystemObjectStore
    from ..storage.relational.sqlite import SQLiteRelationalStore
    from ..storage.vector.base import VectorStore
    from ..storage.vector.chromadb import ChromaVectorStore
    from ..storage.vector.inmemory import InMemoryVectorStore
    from ..utils.text import HashingEmbedder
    from ..utils.ollama import ensure_ollama_running
except ImportError:
    import sys

    _src_root = Path(__file__).resolve().parents[2]
    if str(_src_root) not in sys.path:
        sys.path.insert(0, str(_src_root))

    from rag_self_knowledge.core.chunking.fixed_size import FixedSizeChunker
    from rag_self_knowledge.storage.object_store.filesystem import FileSystemObjectStore
    from rag_self_knowledge.storage.relational.sqlite import SQLiteRelationalStore
    from rag_self_knowledge.storage.vector.base import VectorStore
    from rag_self_knowledge.storage.vector.chromadb import ChromaVectorStore
    from rag_self_knowledge.storage.vector.inmemory import InMemoryVectorStore
    from rag_self_knowledge.utils.text import HashingEmbedder
    from rag_self_knowledge.utils.ollama import ensure_ollama_running

@dataclass(frozen=True)
class Settings:
    """
    运行配置（可被调用方覆盖）。

    说明：
    - frozen=True：配置对象不可变，避免被业务逻辑无意修改造成“隐式全局状态”。
    """
    sqlite_path: Path = Path(__file__).parent.parent.parent / "storage_data" / "relational_data" / "rag_self_knowledge.sqlite3"
    # SQLite 数据库文件路径：
    # - 用于落地 table.md 中关系库表的 SQLite 版（DDL 见 storage/relational/ddl.py）
    blobs_root: Path = Path(__file__).parent.parent.parent / "storage_data" / "object_data"
    # 对象存储根目录（文件系统模式）：
    # - 对齐 table.md 5 的 blobs 目录规范
    embedding_dim: int = 1024
    # embedding 向量维度：
    # - 最小实现使用 HashingEmbedder 生成定长向量
    # - 真实 embedding 模型通常有固定维度（如 768/1024/1536），后续可在这里对齐
    chunk_size: int = 512
    # Chunker 分块大小（字符级）：
    # - MVP 使用固定大小切分；后续若按 token 切分，可将语义改为 token 数
    chunk_overlap: int = 100
    # Chunk 之间的重叠长度（字符级）：
    # - 用于减少跨块断裂导致的召回损失
    # - 必须 < chunk_size
    sentence_transformer_model_path: Path | None = (Path(__file__).parents[2] / 'models--embaas--sentence-transformers-e5-large-v2\snapshots\86001e787b4f6bda8cdc8c2095c0493dd135484e')
    # 可选：Sentence-Transformers 本地模型目录。
    # - 设为 None 时默认使用 HashingEmbedder（不依赖外部模型与三方库）
    # - 设为本地目录时，将尝试加载 sentence_transformers.SentenceTransformer
    enable_summary_index: bool = False
    enable_subq_index: bool = False
    summary_group_size: int = 5
    summary_max_chars: int = 800
    subq_per_chunk: int = 3
    min_score: float = 0.0 # 最小过滤相关性分数
    enable_diversity: bool = True # 是否使用多样性算法
    diversity_key: str = "doc_id" # 多样性分桶的key
    vector_root: Path = Path(__file__).parent.parent.parent / "storage_data" / "vector_data"


class Embedder(Protocol):
    """
    向量化接口协议。

    说明：
    - 只约束最小能力：输入文本 → 输出 embedding 向量（list[float]）
    """
    def embed(self, text: str) -> list[float]: ...

    def embed_batch(self, text: list[str]) -> list[list[float]]: ...


class LLMClient(Protocol):
    def summarize(self, text: str, *, max_chars: int) -> str: ...

    def generate_subquestions(self, text: str, *, n: int) -> list[str]: ...


@dataclass
class DefaultLLMClient(LLMClient):
    OLLAMA_HOST = "http://127.0.0.1:11434"
    url = f"{OLLAMA_HOST}/api/chat"
    check = True

    def summarize(self, text: str, *, max_chars: int) -> str:
        if not self.check: # 确保ollama启动
            run = ensure_ollama_running()
            self.check = run
        base = self.ollama_summarize(text)
        return base[: max(1, int(max_chars))]

    def generate_subquestions(self, text: str, *, n: int) -> list[str]:
        if not self.check: # 确保ollama启动
            run = ensure_ollama_running()
            self.check = run
        snippet = (text or "").strip().replace("\n", " ")
        base = self.ollama_subq(snippet)
        if isinstance(base, str):
            return []
        return base[: max(1, int(n))]

    def ollama_summarize(self, doc):
        '''使用ollama生成摘要'''
        messages = [
            {
                "role": "system",
                "content": "你是一个AI语言模型助手。你的任务为根据用户传入的文档，对内容的主要含义进行摘要，限制在250字以内，以便帮助向量数据库召回文档。"
                           "只返回摘要，不要提供其他额外说明。"
            },
            {
                "role": "user",
                "content": f"给定的文档为: {doc}"
            }
        ]
        # 构造请求数据
        data = {
            "model": "qwen3:14b",
            "messages": messages,
            "stream": False,  # 关闭流式输出
            "think": False,  # 关闭深度思考
        }
        try:
            # 发送POST请求
            response = requests.post(
                self.url,
                json=data,
                headers={"Content-Type": "application/json"}
            )
            response.raise_for_status()  # 检查HTTP错误
            # 解析并输出响应
            result = response.json()
            content = result["message"]["content"].strip()
            return content
        except requests.exceptions.RequestException as e:
            print(f"HTTP Error: {e}")
            return ""

    def ollama_subq(self, doc):
        '''使用ollama生成子问题'''
        messages = [
            {
                "role": "system",
                "content": "你是一个AI语言模型助手。你的任务为根据用户传入的文档，产生五个不同角度的问题，以便帮助向量数据库召回文档。"
                           "你的目标为帮助用户克服基于距离的相关性搜索的限制。每个给出的问题以新行隔开，不要提供其他额外说明。"
            },
            {
                "role": "user",
                "content": f"给定的文档为: {doc}"
            }
        ]
        # 构造请求数据
        data = {
            "model": "qwen3:14b",
            "messages": messages,
            "stream": False,  # 关闭流式输出
            "think": False,  # 关闭深度思考
        }
        try:
            # 发送POST请求
            response = requests.post(
                self.url,
                json=data,
                headers={"Content-Type": "application/json"}
            )
            response.raise_for_status()  # 检查HTTP错误
            # 解析并输出响应
            result = response.json()
            content = result["message"]["content"]
            content = [x.strip() for x in content.split('\n')]
            return content
        except requests.exceptions.RequestException as e:
            print(f"HTTP Error: subq {e}")
            return ""


@dataclass
class SentenceTransformerEmbedder(Embedder):
    model_path: Path

    def __post_init__(self) -> None:
        if not self.model_path.exists():
            raise FileNotFoundError(str(self.model_path))
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer(str(self.model_path))
        self.model = model

    def embed(self, text: str) -> list[float]:
        return self.model.encode(text).tolist()

    def embed_batch(self, text: list[str]) -> list[list[float]]:
        return self.model.encode(text).tolist()


@dataclass(frozen=True)
class RagServices:
    """
    依赖装配容器（Service Container）。

    使用方式：
    - 调用层函数允许传入 services 以覆盖默认依赖，实现“可插拔后端”
    - 例如：将 relational 替换为 PostgreSQL，将 vector 替换为 Qdrant，将 embedder 替换为真实模型
    """
    settings: Settings
    # Settings 配置对象（路径、chunk 参数、embedding 维度等）
    relational: SQLiteRelationalStore
    # 关系库存储（MVP 为 SQLite）
    vector: VectorStore
    object_store: FileSystemObjectStore
    # 对象存储（MVP 为文件系统；后续替换为 MinIO/S3）
    chunker: FixedSizeChunker
    # 文档切分器（MVP 为固定长度分块）
    embedder: Embedder
    # 向量化器（MVP 为 HashingEmbedder；后续替换为真实 embedding 模型）
    llm_client: LLMClient


_SERVICES_CACHE: dict[Settings, RagServices] = {} # 同一组 Settings 在同一进程内复用同一套 services，避免重复创建导致状态丢失


def create_default_services(*, settings: Settings | None = None) -> RagServices:
    """
    创建默认依赖装配（最小可运行闭环）。

    参数：
    - settings：可选，传入以覆盖默认 Settings（例如指定 sqlite_path/blobs_root）

    返回：
    - RagServices：一组可直接用于 add_documents/search_knowledge 的依赖实例
    """
    resolved_settings = settings or Settings()
    cached = _SERVICES_CACHE.get(resolved_settings)
    if cached is not None:
        return cached
    # 如果未提供 settings，则使用默认配置；提供时直接使用调用方传入的配置。

    relational = SQLiteRelationalStore(db_path=resolved_settings.sqlite_path)
    # 初始化关系库（创建表结构）。此操作应可重复执行（DDL 幂等）。
    relational.initialize()

    try:
        vector = ChromaVectorStore(
            persist_directory=str(resolved_settings.vector_root)
        )
    except Exception:
        vector = InMemoryVectorStore()
    object_store = FileSystemObjectStore(root=resolved_settings.blobs_root)
    # 初始化对象存储（文件系统版）：chunk 正文会写入 blobs_root 下的规范路径。
    chunker = FixedSizeChunker(
        chunk_size=resolved_settings.chunk_size, overlap=resolved_settings.chunk_overlap
    )
    # 初始化 Chunker：按固定长度切分正文为 chunk，并设置 overlap 以减少跨块断裂。
    if resolved_settings.sentence_transformer_model_path is not None:
        embedder: Embedder = SentenceTransformerEmbedder(
            model_path=resolved_settings.sentence_transformer_model_path
        )
    else:
        embedder = HashingEmbedder(dim=resolved_settings.embedding_dim)
    # 初始化 Embedder：
    # - 优先使用 SentenceTransformerEmbedder（如提供本地模型路径）
    # - 否则使用 HashingEmbedder（无外部依赖的最小实现）
    llm_client: LLMClient = DefaultLLMClient()

    services = RagServices(
        settings=resolved_settings,
        relational=relational,
        vector=vector,
        object_store=object_store,
        chunker=chunker,
        embedder=embedder,
        llm_client=llm_client,
    )
    _SERVICES_CACHE[resolved_settings] = services
    return services
