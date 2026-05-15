import os
import time
import json
import random
from urllib.request import Request, urlopen
from claude_agent.config import AgentConfig
from dataclasses import dataclass

from typing import Any, TypeVar, Callable, Optional

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

    def fetch_llm():
        with urlopen(req, timeout=90) as resp: # 用urlopen发送Request请求
            body = resp.read().decode("utf-8", errors="replace")
            return body

    try:  # 网络错误时返回错误消息，不中断主流程
        body = retry_call(fetch_llm)
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



T = TypeVar("T") # 范形变量：代表任意返回值类型

@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3 # 最大重试3次
    base_delay_s: float = 0.8 # 基础等待0.8秒
    max_delay_s: float = 6.0 # 最大等待6秒
    backoff: float = 2.0 # 指数倍数：每次×2
    jitter_s: float = 0.25 # 随机抖动±0.25秒


def _exc_name(e: BaseException) -> str:
    '''拿到异常的类名，例如 TimeoutError'''
    return e.__class__.__name__

def is_retriable_exception(e: BaseException) -> bool:
    """
    Heuristic retry classifier.

    We avoid importing provider-specific exception classes (they vary by package version).
    Instead we match common exception names / messages.
    """
    name = _exc_name(e)
    msg = str(e).lower()

    # 网络错误
    transient_names = {
        "TimeoutError",
        "ReadTimeout",
        "ConnectTimeout",
        "ConnectionError",
        "RemoteDisconnected",
        "ProtocolError",
        "SSLError",
        "HTTPError"
    }
    if name in transient_names:
        return True

    # AI服务商限流/过载
    providerish = (
        "RateLimit",
        "RateLimitError",
        "APITimeout",
        "APITimeoutError",
        "APIConnectionError",
        "ServiceUnavailable",
        "ServiceUnavailableError",
        "InternalServerError",
        "BadGateway",
        "GatewayTimeout",
        "Unavailable",
    )
    if any(tok in name for tok in providerish):
        return True

    # HTTP状态码
    if any(s in msg for s in ("429", "rate limit", "too many requests")):
        return True
    if any(s in msg for s in ("503", "service unavailable", "temporarily unavailable")):
        return True
    if any(s in msg for s in ("502", "bad gateway")):
        return True
    if any(s in msg for s in ("504", "gateway timeout")):
        return True

    # 超时关键词
    if "timeout" in msg or "timed out" in msg:
        return True

    return False

def _sleep_for_attempt(policy: RetryPolicy, attempt: int) -> None:
    delay = min(policy.max_delay_s, policy.base_delay_s * (policy.backoff ** (attempt - 1)))
    delay = max(0.0, delay + random.uniform(0.0, policy.jitter_s))
    time.sleep(delay)

def retry_call(
    fn: Callable[[], T], # 要执行的函数
    *,
    policy: RetryPolicy = RetryPolicy(),
    retriable: Callable[[BaseException], bool] = is_retriable_exception,
) -> T:
    last: Optional[BaseException] = None

    # 循环尝试最多 max_attempts 次
    for attempt in range(1, policy.max_attempts + 1):
        try:
            return fn() # 执行函数 → 成功就返回
        except BaseException as e:
            last = e
            # 如果达到最大次数 或 错误不允许重试 → 抛出
            if attempt >= policy.max_attempts or not retriable(e):
                raise
            # 否则等待 → 重试
            _sleep_for_attempt(policy, attempt)
    # unreachable, 最终失败，抛出最后一次异常
    if last is not None:
        raise last
    raise RuntimeError("retry_call failed without exception")