import os
import json
from typing import Any
from urllib.request import Request, urlopen
from claude_agent.config import AgentConfig

config = AgentConfig()

def call_model(
        model_name:str,
        *,
        system_prompt: str,
        user_prompt: str,
        tools: list[dict[str, Any]],
        tool_choice: str,
) -> dict[str, Any]:
    api_key = ""
    url = ""
    if model_name == "deepseek-chat":
        api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip() or config.deepseek_key
        url = "https://api.deepseek.com/v1/chat/completions"
    elif model_name == "qwen-plus":
        api_key = os.environ.get("QWEN_API_KEY", "").strip() or config.qwen_key
        url = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    elif model_name == "glm-5":
        api_key = os.environ.get("GLM_API_KEY", "").strip() or config.glm_key
        url = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
    elif model_name == "kimi-k2.6":
        api_key = os.environ.get("KIMI_API_KEY", "").strip() or config.kimi_key
        url = "https://api.moonshot.cn/v1/chat/completions"
    else:
        api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").strip().rstrip("/")
        url = f"{base}/chat/completions"

    if not api_key or not url:
        hint = []
        hint.append("LLM is not configured (missing API key).")
        hint.append(f"model: {model_name}")
        hint.append("Set one of these environment variables then restart the server:")
        if model_name == "deepseek-chat":
            hint.append("- DEEPSEEK_API_KEY")
        elif model_name == "qwen-plus":
            hint.append("- QWEN_API_KEY")
        elif model_name == "glm-5":
            hint.append("- GLM_API_KEY")
        elif model_name == "kimi-k2.6":
            hint.append("- KIMI_API_KEY")
        else:
            hint.append("- OPENAI_API_KEY (and optionally OPENAI_BASE_URL)")
        return {"role": "assistant", "content": "\n".join(hint), "tool_calls": []}

    payload: dict[str, Any] = {
        "model": model_name,
        "temperature": float(config.temperature),
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = tool_choice

    req = Request(  # 向LLM发送请求
        url=url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    try:  # 网络错误时返回错误消息，不中断主流程
        with urlopen(req, timeout=90) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        return {"role": "assistant", "content": f"[Model call failed] {e!r}", "tool_calls": []}
    try:  # 安全解析响应
        data = json.loads(body)
    except Exception:
        return {"role": "assistant", "content": body, "tool_calls": []}
    msg = (((data.get("choices") or [None])[0]) or {}).get("message") or {}
    if isinstance(msg, dict):
        return dict(msg)
    return {"role": "assistant", "content": str(msg), "tool_calls": []}
