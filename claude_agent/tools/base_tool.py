from __future__ import annotations

from abc import ABC, abstractmethod
import json
from typing import Any, Dict, Type

from pydantic import BaseModel


class BaseTool(ABC):
    """
    所有工具的统一基类
    包含：名称、描述、输入Schema、安全检查、执行逻辑
    """

    name: str
    search_hint: str
    description: str
    input_schema: Type[BaseModel]
    output_schema: Type[BaseModel]
    needs_permission: bool = False

    @abstractmethod
    def execute(self, **kwargs: Any) -> BaseModel:
        """
        工具执行逻辑（子类必须实现）
        """
        raise NotImplementedError

    def validate_security(self, **kwargs: Any) -> None:
        """
        统一安全校验入口
        所有工具执行前必须调用
        """
        return

    def validate_permission(self, **kwargs: Any) -> None:
        if not self.needs_permission:
            return
        confirmed = bool(kwargs.get("confirmed", False))
        if confirmed:
            return
        raise PermissionError(
            json.dumps(
                {
                    "decision": "confirm",
                    "reason": "Tool requires permission.",
                    "tool": self.name,
                },
                ensure_ascii=False,
            )
        )

    def run(self, **kwargs: Any) -> str:
        '''run外部调用的唯一入口'''
        payload = self.input_schema(**kwargs) # 1. 用Pydantic模型校验并清洗输入
        data = payload.model_dump()
        self.validate_security(**data) # 2 & 3. 执行安全与权限检查
        self.validate_permission(**data)
        result = self.execute(**data) # 4. 调用子类的具体实现
        return result.model_dump_json(ensure_ascii=False)

    def to_openai_tool(self) -> Dict[str, Any]:
        """
        转为 OpenAI 函数调用格式（给LLM用）
        """
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema.model_json_schema(),
            },
        }
