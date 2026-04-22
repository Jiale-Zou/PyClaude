from __future__ import annotations

import importlib
import json
import math
import pkgutil
import re
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from claude_agent.tools.base_tool import BaseTool


class ToolSearchInput(BaseModel):
    query: str # 搜索关键词


class ToolSearchOutput(BaseModel):
    ok: bool # 搜索是否成功
    tool_name: str | None = None # 匹配到的工具名称
    score: float = 0.0 # 相关性得分 (0-1)
    tool: dict[str, Any] | None = None # 工具的完整使用说明
    message: str | None = None # 错误或提示信息


def _tokenize(text: str) -> list[str]:
    if not text:
        return []
    text = text.lower()
    words = re.findall(r"[a-z0-9_]+", text) # 提取英文单词、数字、下划线
    cjk = re.findall(r"[\u4e00-\u9fff]", text) # 提取中文汉字
    return words + cjk


def _tf(tokens: list[str]) -> dict[str, float]:
    '''TF词频计算'''
    if not tokens:
        return {}
    counts: dict[str, int] = {}
    for t in tokens:
        counts[t] = counts.get(t, 0) + 1
    total = float(len(tokens))
    return {k: v / total for k, v in counts.items()}


def _idf(corpus_tokens: list[list[str]]) -> dict[str, float]:
    '''IDF逆文档频率计算'''
    n = len(corpus_tokens)
    df: dict[str, int] = {}
    for doc in corpus_tokens:
        for t in set(doc): # 每个词在一个文档中只计一次
            df[t] = df.get(t, 0) + 1
    # 平滑处理：分母 +1 避免除零
    return {t: math.log((n + 1.0) / (df_t + 1.0)) + 1.0 for t, df_t in df.items()}


def _tfidf_vec(tokens: list[str], idf: dict[str, float]) -> dict[str, float]:
    '''TF-IDF 向量'''
    tf = _tf(tokens)
    vec: dict[str, float] = {}
    for t, w in tf.items():
        vec[t] = w * idf.get(t, 0.0)
    return vec


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    '''余弦相似度计算'''
    if not a or not b:
        return 0.0
    dot = 0.0
    for k, v in a.items():
        dot += v * b.get(k, 0.0)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _name_match_score(query: str, name: str) -> float:
    '''名称匹配加分'''
    q = (query or "").strip().lower()
    n = (name or "").strip().lower()
    if not q or not n:
        return 0.0
    if q == n:
        return 1.0
    if q in n or n in q:
        return 1.0
    return 0.0


def _iter_lazy_tool_classes() -> list[type[BaseTool]]:
    '''动态扫描 claude_agent.tools.lazy_tools 包，自动发现所有继承自 BaseTool 的工具类'''
    import claude_agent.tools.lazy_tools as lazy_pkg

    tools: list[type[BaseTool]] = []
    for modinfo in pkgutil.iter_modules(lazy_pkg.__path__, lazy_pkg.__name__ + "."): # 遍历 lazy_tools 包中的所有模块
        try:
            module = importlib.import_module(modinfo.name)
        except Exception:
            continue
        for obj in vars(module).values(): # 查找所有 BaseTool 的子类
            if isinstance(obj, type) and issubclass(obj, BaseTool) and obj is not BaseTool:
                tools.append(obj)
    return tools


def _tool_prompt_dict(tool: BaseTool) -> dict[str, Any]:
    '''生成工具的完整使用说明，供 LLM 理解如何调用该工具'''
    return {
        "name": tool.name,
        "search_hint": tool.search_hint,
        "description": tool.description,
        "needs_permission": bool(getattr(tool, "needs_permission", False)),
        "input_schema": tool.input_schema.model_json_schema(),
        "output_schema": tool.output_schema.model_json_schema(),
    }


@dataclass(slots=True)
class ToolSearchTool(BaseTool):
    name: str = "tool_search"
    search_hint: str = "根据关键词搜索最匹配的其他工具并输出使用说明"
    description: str = "Search other available tools by keyword and return the best matching tool usage specification."
    input_schema = ToolSearchInput
    output_schema = ToolSearchOutput
    needs_permission: bool = False

    def execute(self, **kwargs: Any) -> BaseModel:
        query = str(kwargs.get("query", "")).strip() # 1. 获取并校验查询词
        if not query:
            return ToolSearchOutput(ok=False, message="Empty query.")

        tool_classes = _iter_lazy_tool_classes() # 2. 动态发现所有懒加载工具类
        if not tool_classes:
            return ToolSearchOutput(ok=False, message="No lazy tools available.")

        candidates: list[BaseTool] = [] # 3. 实例化工具
        for cls in tool_classes:
            try:
                candidates.append(cls())
            except Exception:
                continue
        if not candidates:
            return ToolSearchOutput(ok=False, message="No instantiable lazy tools available.")

        hint_docs = [_tokenize(t.search_hint) for t in candidates] # 4. 构建 TF-IDF 索引
        desc_docs = [_tokenize(t.description) for t in candidates]
        idf_hint = _idf(hint_docs + [_tokenize(query)])
        idf_desc = _idf(desc_docs + [_tokenize(query)])
        q_vec_hint = _tfidf_vec(_tokenize(query), idf_hint)
        q_vec_desc = _tfidf_vec(_tokenize(query), idf_desc)

        best: tuple[float, BaseTool] | None = None # 5. 计算每个工具的相关性得分
        for t in candidates:
            s1 = _name_match_score(query, t.name)
            s2 = _cosine(q_vec_hint, _tfidf_vec(_tokenize(t.search_hint), idf_hint))
            s3 = _cosine(q_vec_desc, _tfidf_vec(_tokenize(t.description), idf_desc))
            score = 0.5 * s1 + 0.3 * s2 + 0.2 * s3
            if best is None or score > best[0]:
                best = (score, t)

        if best is None or best[0] <= 0.0: # 6. 返回结果
            return ToolSearchOutput(ok=False, message="No matching tool.")

        score, tool = best
        return ToolSearchOutput(ok=True, tool_name=tool.name, score=float(score), tool=_tool_prompt_dict(tool))
