from __future__ import annotations

import base64
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from claude_agent.tools.base_tool import BaseTool


class FileReadInput(BaseModel):
    file_path: str # 必需：要读取的文件路径
    encoding: str = "utf-8" # 文本编码，默认 UTF-8
    max_bytes: int = 2_000_000 # 二进制文件最大读取字节数（约2MB）
    max_chars: int = 20_000 # 文本文件最大读取字符数（约2万个字符）
    confirmed: bool = False


class FileReadOutput(BaseModel):
    path: str # 回显文件路径
    kind: str # 文件类型："text" / "binary" / "error"
    encoding: str | None = None # 文本文件的编码
    content: str | None = None # 文本内容
    data_base64: str | None = None # 二进制内容的 Base64 编码
    mime: str | None = None # MIME 类型（如 "image/png"）
    truncated: bool = False  # 内容是否因超限而被截断


@dataclass(slots=True)
class FileReadTool(BaseTool):
    name: str = "file_read"
    search_hint: str = "读取本地文件内容，支持文本/图片/PDF/Office并做大小截断"
    description: str = "Read a file from disk, such as picture, pdf, .docx, excel, txt and many other types of files."
    input_schema = FileReadInput
    output_schema = FileReadOutput
    needs_permission: bool = False

    def execute(self, **kwargs: Any) -> BaseModel:
        path = Path(str(kwargs["file_path"]))
        if not path.exists() or not path.is_file(): # 检查文件是否存在且为普通文件（非目录、链接等）
            return FileReadOutput(path=str(path), kind="error", content=f"File not found: {path}")

        max_bytes = int(kwargs.get("max_bytes", 2_000_000))  # 获取大小限制参数
        max_chars = int(kwargs.get("max_chars", 20_000))

        suffix = path.suffix.lower() # 尝试根据文件扩展名推断 MIME 类型
        mime, _ = mimetypes.guess_type(str(path))
        if mime is None:
            mime = "application/octet-stream"
        # 1. 硬编码的二进制文件扩展名列表（常见图片和PDF格式）
        if suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".pdf"}:
            data = path.read_bytes() # 以字节形式读取
            truncated = False
            if len(data) > max_bytes: # 应用大小限制
                data = data[:max_bytes]
                truncated = True
            return FileReadOutput( # 返回 Base64 编码后的数据
                path=str(path),
                kind="binary",
                data_base64=base64.b64encode(data).decode("ascii"),
                mime=mime,
                truncated=truncated,
            )

        if suffix == ".docx": # 2. docx
            try:
                from docx import Document

                doc = Document(str(path))
                full_text = "\n".join([para.text for para in doc.paragraphs])
                truncated = False
                if len(full_text) > max_chars:
                    full_text = full_text[:max_chars]
                    truncated = True
                return FileReadOutput(
                    path=str(path),
                    kind="text",
                    encoding="docx-internal",
                    content=full_text,
                    truncated=truncated,
                )
            except Exception as e:
                return FileReadOutput(
                    path=str(path),
                    kind="error",
                    content=f"Failed to read docx: {e}",
                )

        if suffix in {".xls", ".xlsx"}: # 3. xlsx/xls
            try:
                import pandas as pd

                df = pd.read_excel(str(path), engine=None) # 读取整个 Excel 文件，默认读取第一个 sheet
                full_text = df.to_string(index=False) # 将 DataFrame 转换为文本格式，便于后续处理
                truncated = False
                if len(full_text) > max_chars:
                    full_text = full_text[:max_chars]
                    truncated = True
                return FileReadOutput(
                    path=str(path),
                    kind="text",
                    encoding="xlsx-internal",
                    content=full_text,
                    truncated=truncated,
                )
            except Exception as e:
                return FileReadOutput(
                    path=str(path),
                    kind="error",
                    content=f"Failed to read xlsx: {e}",
                )
        # 4. 非上述二进制类型，一律按文本文件处理（遇到无法解码的字符，用 � 替代，避免抛出异常）
        text = path.read_text(encoding=str(kwargs.get("encoding", "utf-8")), errors="replace")
        truncated = False
        if len(text) > max_chars: # 应用字符数限制
            text = text[:max_chars]
            truncated = True
        return FileReadOutput(path=str(path), kind="text", encoding=str(kwargs.get("encoding", "utf-8")), content=text, truncated=truncated)
