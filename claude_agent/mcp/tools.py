from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from claude_agent.mcp.client import MCPClient
from claude_agent.tools.base_tool import BaseTool


class MCPCallInput(BaseModel):
    service_name: str # 要调用的 MCP 服务名称
    params: dict[str, Any] = Field(default_factory=dict) # 传递给服务的参数
    timeout_sec: int = 30 # 超时时间，默认30秒


class MCPCallOutput(BaseModel):
    ok: bool # 调用是否成功
    service: str # 回显服务名称
    data: dict[str, Any] | None = None # 成功时返回的数据
    error: str | None = None # 失败时的错误信息


@dataclass(slots=True)
class MCPCallTool(BaseTool):
    name: str = "mcp_call"
    description: str = "Call an external MCP service."
    input_schema = MCPCallInput
    output_schema = MCPCallOutput
    needs_permission: bool = False
    config_path: Path = Path(__file__).resolve().parent / "config.json"

    def execute(self, **kwargs: Any) -> BaseModel:
        client = MCPClient(config_path=self.config_path) # 1. 创建 MCPClient 实例
        resp = client.call_mcp( # 2. 调用 MCP 服务
            service_name=str(kwargs["service_name"]),
            params=dict(kwargs.get("params") or {}),
            timeout_sec=int(kwargs.get("timeout_sec", 30)),
        )
        if bool(resp.get("ok")):  # 3. 根据调用结果构造输出
            return MCPCallOutput(ok=True, service=str(resp.get("service", "")), data=dict(resp.get("data") or {}))
        return MCPCallOutput(ok=False, service=str(resp.get("service", "")), error=str(resp.get("error", "")))
