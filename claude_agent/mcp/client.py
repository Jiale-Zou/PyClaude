from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen


def load_mcp_config(config_path: Path) -> dict[str, Any]:
    try:
        return json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return {"enabled": False, "services": []}


@dataclass(slots=True)
class MCPClient:
    config_path: Path

    def _service(self, service_name: str) -> dict[str, Any] | None:
        cfg = load_mcp_config(self.config_path)
        if not bool(cfg.get("enabled", False)): # 1. 检查MCP总开关
            return None
        for s in cfg.get("services", []) or []: # 2. 遍历服务列表，查找匹配且启用的服务
            if str(s.get("name", "")) == service_name and bool(s.get("enabled", True)):
                return dict(s)
        return None

    def call_mcp(self, service_name: str, params: dict[str, Any], timeout_sec: int = 30) -> dict[str, Any]:
        service = self._service(service_name)
        if service is None: # 如果服务不存在或未启用，返回统一的错误格式
            return {"ok": False, "error": "MCP service not enabled or not found.", "service": service_name}

        url = str(service.get("url", "")).strip()
        if not url: # 确保服务配置中包含有效的URL
            return {"ok": False, "error": "MCP service URL missing.", "service": service_name}

        api_key = str(service.get("api_key", "")).strip()
        headers = {"Content-Type": "application/json"}
        if api_key: # 处理API密钥认证
            headers["Authorization"] = f"Bearer {api_key}"
        # 构建请求体
        payload = json.dumps({"service": service_name, "params": params}, ensure_ascii=False).encode("utf-8")
        req = Request(url=url, data=payload, headers=headers, method="POST")
        try:
            with urlopen(req, timeout=timeout_sec) as resp:
                body = resp.read().decode("utf-8", errors="replace")
        except Exception as e:
            return {"ok": False, "error": repr(e), "service": service_name}

        try:
            data = json.loads(body)
        except Exception:
            data = {"raw": body}
        return {"ok": True, "service": service_name, "data": data}
