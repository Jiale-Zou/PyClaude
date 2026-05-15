from __future__ import annotations

import base64
import io
from pathlib import Path
from urllib.parse import quote
import zipfile
from xml.etree import ElementTree as ET

from fastapi import APIRouter
from pydantic import BaseModel

from claude_agent.api.dependencies import get_state
from claude_agent.prompt.user_profile import ensure_user_memory

router = APIRouter(tags=["memory"])


@router.get("/users/{user_id}/memory")
def get_memory(user_id: str) -> dict[str, object]:
    return {"user_id": user_id, "items": []}


@router.get("/files/config")
def get_config_file() -> dict[str, str]:
    p = Path(__file__).resolve().parents[2] / "config.py"
    try:
        content = p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        content = ""
    return {"path": str(p), "content": content}


@router.get("/users/{user_id}/files/memory")
def get_user_memory_file(user_id: str) -> dict[str, str]:
    storage_root = Path(get_state().config.storage_dir)
    p = ensure_user_memory(storage_root, user_id)
    try:
        content = p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        content = ""
    return {"path": str(p), "content": content}


class SaveTextRequest(BaseModel):
    content: str


@router.put("/users/{user_id}/files/memory")
def save_user_memory_file(user_id: str, req: SaveTextRequest) -> dict[str, object]:
    storage_root = Path(get_state().config.storage_dir)
    p = ensure_user_memory(storage_root, user_id)
    p.write_text(str(req.content), encoding="utf-8")
    return {"ok": True, "path": str(p)}


def _rag_user_root(user_id: str) -> Path:
    return Path(__file__).resolve().parents[2] / "rag" / "storage_data" / user_id


def _rag_user_settings(user_id: str):
    from claude_agent.rag.rag_self_knowledge.config.settings import Settings

    base = _rag_user_root(user_id)
    default = Settings()
    return Settings(
        sqlite_path=base / "relational_data" / "rag_self_knowledge.sqlite3",
        blobs_root=base / "object_data",
        vector_root=base / "vector_data",
        embedding_dim=default.embedding_dim,
        chunk_size=default.chunk_size,
        chunk_overlap=default.chunk_overlap,
        sentence_transformer_model_path=default.sentence_transformer_model_path,
        enable_summary_index=default.enable_summary_index,
        enable_subq_index=default.enable_subq_index,
        summary_group_size=default.summary_group_size,
        summary_max_chars=default.summary_max_chars,
        subq_per_chunk=default.subq_per_chunk,
        min_score=default.min_score,
        enable_diversity=default.enable_diversity,
        diversity_key=default.diversity_key,
    )


def _kb_source_filename(kb_name: str) -> str:
    safe = quote(str(kb_name), safe="")
    if not safe:
        safe = "kb"
    return safe + ".txt"


def _load_kb_source_text(user_id: str, kb_name: str) -> str:
    root = _rag_user_root(user_id) / "kb_sources"
    p = root / _kb_source_filename(kb_name)
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        legacy = root / f"{kb_name}.txt"
        try:
            return legacy.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return ""


def _write_kb_source_text(user_id: str, kb_name: str, content: str) -> str:
    p = _rag_user_root(user_id) / "kb_sources" / _kb_source_filename(kb_name)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(str(content), encoding="utf-8")
    return str(p)


def _delete_kb_source_text(user_id: str, kb_name: str) -> None:
    root = _rag_user_root(user_id) / "kb_sources"
    for p in [root / _kb_source_filename(kb_name), root / f"{kb_name}.txt"]:
        try:
            if p.exists():
                p.unlink()
        except Exception:
            pass


class KBCreateRequest(BaseModel):
    kb_name: str
    description: str = ""
    content: str = ""


class KBUpdateRequest(BaseModel):
    description: str | None = None
    content: str | None = None


class ExtractTextRequest(BaseModel):
    filename: str = ""
    data_base64: str = ""


@router.post("/users/{user_id}/rag/extract-text")
def extract_text(user_id: str, req: ExtractTextRequest) -> dict[str, object]:
    filename = str(req.filename or "")
    data_b64 = str(req.data_base64 or "")
    if not data_b64:
        return {"ok": False, "filename": filename, "error": "Empty data.", "content": ""}
    try:
        data = base64.b64decode(data_b64, validate=False)
    except Exception as e:
        return {"ok": False, "filename": filename, "error": f"Base64 decode failed: {e!r}", "content": ""}

    lower = filename.lower()
    if lower.endswith(".docx"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                xml = z.read("word/document.xml")
            root = ET.fromstring(xml)
            texts: list[str] = []
            for node in root.iter():
                if node.tag.endswith("}t") and node.text:
                    texts.append(node.text)
                if node.tag.endswith("}p"):
                    texts.append("\n")
            content = "".join(texts).replace("\n\n\n", "\n\n").strip()
            return {"ok": True, "filename": filename, "content": content}
        except Exception as e:
            return {"ok": False, "filename": filename, "error": f"Parse docx failed: {e!r}", "content": ""}

    try:
        content = data.decode("utf-8", errors="replace")
    except Exception:
        content = ""
    return {"ok": True, "filename": filename, "content": content}


@router.get("/users/{user_id}/rag/kbs")
def list_kbs(user_id: str) -> dict[str, object]:
    from claude_agent.rag.rag_self_knowledge.api import list_knowledge_bases
    from claude_agent.rag.rag_self_knowledge.config.settings import create_default_services

    services = create_default_services(settings=_rag_user_settings(user_id))
    return {"user_id": user_id, "items": list_knowledge_bases(services=services)}


@router.get("/users/{user_id}/rag/kbs/{kb_name}")
def get_kb(user_id: str, kb_name: str) -> dict[str, object]:
    from claude_agent.rag.rag_self_knowledge.config.settings import create_default_services

    services = create_default_services(settings=_rag_user_settings(user_id))
    items = services.relational.list_knowledge_bases()
    desc = ""
    kb_id = ""
    for it in items:
        if str(it.get("kb_name", "")) == kb_name:
            desc = str(it.get("description") or "")
            kb_id = str(it.get("kb_id") or "")
            break

    content = _load_kb_source_text(user_id, kb_name)
    if not content and kb_id:
        source = f"kb://{kb_name}/main"
        doc = services.relational.get_document_by_source(kb_id=kb_id, source=source)
        if doc is not None:
            doc_id = str(doc.get("doc_id") or "")
            chunk_ids = services.relational.get_chunk_ids_by_doc(doc_id=doc_id)
            ordered = [cid for _, cid in sorted(chunk_ids.items(), key=lambda kv: kv[0])]
            refs = services.relational.get_chunk_refs(chunk_ids=ordered)
            texts: list[str] = []
            for cid in ordered:
                ref = refs.get(cid, {}).get("text_ref")
                if not ref:
                    continue
                try:
                    texts.append(services.object_store.get_text(ref=ref))
                except Exception:
                    continue
            content = "\n".join(texts).strip()

    return {"user_id": user_id, "kb_name": kb_name, "description": desc, "content": content}


@router.post("/users/{user_id}/rag/kbs")
def create_kb(user_id: str, req: KBCreateRequest) -> dict[str, object]:
    from claude_agent.rag.rag_self_knowledge.api import add_documents
    from claude_agent.rag.rag_self_knowledge.config.settings import create_default_services
    from claude_agent.rag.rag_self_knowledge.models.document import DocumentMetadata

    kb_name = str(req.kb_name or "").strip()
    if not kb_name or "/" in kb_name or "\\" in kb_name:
        return {"ok": False, "error": "Invalid kb_name."}

    services = create_default_services(settings=_rag_user_settings(user_id))
    services.relational.ensure_kb(kb_name=kb_name, description=str(req.description or ""))
    src_path = _write_kb_source_text(user_id, kb_name, str(req.content or ""))
    meta = DocumentMetadata(
        source=f"kb://{kb_name}/main",
        title=kb_name,
        author=user_id,
        custom_fields={"kb_source_path": src_path},
    )
    doc_ids = add_documents(kb_name=kb_name, docs=[str(req.content or "")], metadatas=[meta], services=services)
    return {"ok": True, "kb_name": kb_name, "doc_ids": doc_ids}


@router.put("/users/{user_id}/rag/kbs/{kb_name}")
def update_kb(user_id: str, kb_name: str, req: KBUpdateRequest) -> dict[str, object]:
    from claude_agent.rag.rag_self_knowledge.api import add_documents
    from claude_agent.rag.rag_self_knowledge.config.settings import create_default_services
    from claude_agent.rag.rag_self_knowledge.models.document import DocumentMetadata

    kb_name = str(kb_name or "").strip()
    if not kb_name or "/" in kb_name or "\\" in kb_name:
        return {"ok": False, "error": "Invalid kb_name."}

    services = create_default_services(settings=_rag_user_settings(user_id))
    if req.description is not None:
        services.relational.ensure_kb(kb_name=kb_name, description=str(req.description or ""))
    content = str(req.content or "")
    src_path = _write_kb_source_text(user_id, kb_name, content)
    meta = DocumentMetadata(
        source=f"kb://{kb_name}/main",
        title=kb_name,
        author=user_id,
        custom_fields={"kb_source_path": src_path},
    )
    doc_ids = add_documents(kb_name=kb_name, docs=[content], metadatas=[meta], services=services)
    return {"ok": True, "kb_name": kb_name, "doc_ids": doc_ids}


@router.delete("/users/{user_id}/rag/kbs/{kb_name}")
def delete_kb(user_id: str, kb_name: str) -> dict[str, object]:
    from shutil import rmtree

    from claude_agent.rag.rag_self_knowledge.config.settings import create_default_services

    kb_name = str(kb_name or "").strip()
    if not kb_name or "/" in kb_name or "\\" in kb_name:
        return {"ok": False, "error": "Invalid kb_name."}

    services = create_default_services(settings=_rag_user_settings(user_id))

    kb_id = ""
    for it in services.relational.list_knowledge_bases():
        if str(it.get("kb_name", "")) == kb_name:
            kb_id = str(it.get("kb_id") or "")
            break
    if not kb_id:
        _delete_kb_source_text(user_id, kb_name)
        return {"ok": True, "kb_name": kb_name, "deleted": False}

    try:
        services.relational.delete_kb(kb_id=kb_id)
    except Exception as e:
        return {"ok": False, "error": f"Delete relational failed: {e!r}"}

    obj_dir = _rag_user_root(user_id) / "object_data" / kb_name
    try:
        if obj_dir.exists():
            rmtree(obj_dir, ignore_errors=True)
    except Exception:
        pass

    try:
        if hasattr(services.vector, "delete_collection"):
            prefix = f"kb_{kb_id}"
            services.vector.delete_collection(f"{prefix}_direct")
            services.vector.delete_collection(f"{prefix}_summary")
            services.vector.delete_collection(f"{prefix}_subq")
    except Exception:
        pass

    _delete_kb_source_text(user_id, kb_name)
    return {"ok": True, "kb_name": kb_name, "deleted": True}
