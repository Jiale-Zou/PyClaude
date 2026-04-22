from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TYPE_CHECKING

from claude_agent.config import AgentConfig
from claude_agent.core.context_manager import ContextManager
from claude_agent.tools.base_tool import BaseTool
from claude_agent.model.models import call_model


if TYPE_CHECKING:
    from claude_agent.prompt.prompt_builder import PromptBuilder


def _default_prompt_builder() -> Any:
    from claude_agent.prompt.prompt_builder import PromptBuilder

    return PromptBuilder()


def _tool_sig(tool_name: str, tool_args: dict[str, Any]) -> str:
    '''计算too_name+tool_args的sha256'''
    args = dict(tool_args or {})
    args.pop("confirmed", None)
    return json.dumps(
        {"tool": tool_name, "args": args},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


@dataclass(slots=True)
class QueryEngine:
    config: AgentConfig = field(default_factory=AgentConfig) # Agent配置（模型名称、温度、存储目录等）
    context_manager: ContextManager = field(default_factory=ContextManager) # 上下文管理器，负责token预算控制和消息压缩
    prompt_builder: "PromptBuilder" = field(default_factory=_default_prompt_builder) # 提示词构建器
    messages: list[dict[str, Any]] = field(default_factory=list) # 当前会话的消息历史（role, content格式）
    max_steps: int = 12 # 最大工具调用步数，防止无限循环
    pending_tool: dict[str, Any] | None = None
    executed_tool_sigs: set[str] = field(default_factory=set) # 记录已执行过的参数签名
    tool_result_cache: dict[str, str] = field(default_factory=dict) # sig -> tool.run() 返回的JSON字符串

    def run(
        self,
        user_input: str,
        *,
        user_id: str = "",
        session_id: str = "",
        instructions: str = "",
        subagent: bool = False,
    ) -> str:
        self.context_manager.storage_root = Path(self.config.storage_dir) # 设置存储目录(storage)
        self.prompt_builder.storage_root = Path(self.config.storage_dir)

        if not self.context_manager.within_budget(user_input): # 一、预算检查：如果用户输入超过token预算，进行截断处理。
            user_input = self.context_manager.snip(user_input)

        if subagent: # 二、SubAgent是"纯净版"Agent，只有对话能力，没有工具访问权限，用于：1. 执行被主Agent委托的子任务；2. 避免工具调用深度嵌套
            model_msg = call_model(
                "deepseek-chat",
                system_prompt="You are a sub-agent.\n",
                user_prompt=user_input,
                tools=[],
                tool_choice="none",
            )
            return str(model_msg.get("content") or "").strip()

        if not session_id: # 三、会话标识处理
            session_id = "default"
        if not user_id:
            user_id = "default"

        self.messages.append({"role": "user", "content": user_input})

        tool_registry = self._tool_registry() # 四、工具注册: 获取所有可用工具/转换为OpenAI function calling格式
        tools_spec = [t.to_openai_tool() for t in tool_registry.values()] if tool_registry else []

        final_text = "" # 五、Agentic Loop: 最多执行max_steps轮，防止无限循环。
        for _ in range(max(1, int(self.max_steps))):
            system_prompt, user_prompt = self._build_prompts( # 1. 构建提示词
                user_id=user_id, session_id=session_id, instructions=instructions, subagent=subagent
            )

            model_msg = call_model( # 2. 调用模型
                self.config.model_name,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                tools=tools_spec,
                tool_choice="auto" if tools_spec else "none", # tool_choice="auto"：让模型自主决定是否调用工具
            )

            assistant_text = str(model_msg.get("content") or "").strip() #  3. 处理模型响应
            tool_calls = model_msg.get("tool_calls") or []

            if assistant_text:
                self.messages.append({"role": "assistant", "content": assistant_text})
                final_text = assistant_text

            if not tool_calls:
                break

            executed_any = False
            duplicate_only = True
            for call in tool_calls: # 4. 执行工具调用
                tool_name, tool_args, call_id = self._parse_tool_call(call)
                if not tool_name or tool_name not in tool_registry:
                    self.messages.append(
                        {
                            "role": "tool",
                            "name": tool_name or "unknown_tool",
                            "tool_call_id": call_id,
                            "content": json.dumps(
                                {"ok": False, "error": f"Unknown tool: {tool_name}"},
                                ensure_ascii=False,
                            ),
                        }
                    )
                    continue

                tool = tool_registry[tool_name] # 5. 执行工具
                sig = _tool_sig(tool_name, tool_args)
                cached = self.tool_result_cache.get(sig)
                if cached is not None:
                    self.messages.append({"role": "tool", "name": tool_name, "tool_call_id": call_id, "content": cached})
                    continue
                try:
                    result = tool.run(**tool_args)
                    self.executed_tool_sigs.add(sig)
                    self.tool_result_cache[sig] = result
                    executed_any = True
                    duplicate_only = False
                except PermissionError as e: # 特殊处理：权限错误 → 返回确认请求
                    try:
                        payload = json.loads(str(e))
                    except Exception:
                        payload = {"decision": "confirm", "reason": str(e)}
                    self.pending_tool = {
                        "tool_name": tool_name,
                        "tool_args": dict(tool_args),
                        "tool_call_id": call_id,
                        "sig": sig,
                    }
                    payload["tool"] = tool_name
                    return json.dumps(payload, ensure_ascii=False)
                except Exception as e:
                    result = json.dumps({"ok": False, "error": repr(e)}, ensure_ascii=False)
                    duplicate_only = False

                self.messages.append( # 6. 保存工具结果
                    {"role": "tool", "name": tool_name, "tool_call_id": call_id, "content": result}
                )

            if (not executed_any) and duplicate_only:
                self.messages.append(
                    {
                        "role": "system",
                        "content": "[Loop guard] Tools were repeatedly called with the same arguments and served from cache. Please provide the final answer without calling tools again.",
                    }
                )
                system_prompt2, user_prompt2 = self._build_prompts(
                    user_id=user_id, session_id=session_id, instructions=instructions, subagent=subagent
                )
                model_msg2 = call_model(
                    self.config.model_name,
                    system_prompt=system_prompt2,
                    user_prompt=user_prompt2,
                    tools=[],
                    tool_choice="none",
                )
                assistant_text2 = str(model_msg2.get("content") or "").strip()
                if assistant_text2:
                    self.messages.append({"role": "assistant", "content": assistant_text2})
                    final_text = assistant_text2
                break
        # 六、上下文压缩
        self.messages = self.context_manager.compact_messages(self.messages, user_id=user_id, session_id=session_id)
        # 七、触发记忆系统
        from claude_agent.memory.auto_memory import AutoMemory
        from claude_agent.memory.session_memory import SessionMemory

        AutoMemory(storage_root=self.config.storage_dir, user_id=user_id).on_round_completed() # 增加轮次计数器
        AutoMemory(storage_root=self.config.storage_dir, user_id=user_id).schedule_write(
            [dict(role=str(m.get("role", "")), content=str(m.get("content", ""))) for m in self.messages],
            session_id=session_id,
            force=False,
        ) # 异步写入长期记忆（跨会话）
        SessionMemory(storage_root=self.config.storage_dir, user_id=user_id, session_id=session_id).schedule_write(
            [dict(role=str(m.get("role", "")), content=str(m.get("content", ""))) for m in self.messages]
        ) # 写入会话记忆（仅当前会话）

        return final_text or ""

    def confirm_pending(
        self,
        *,
        user_id: str,
        session_id: str,
        confirmed: bool,
        instructions: str = "",
    ) -> str:
        '''用于用户确认或拒绝之前挂起的工具调用'''
        if self.pending_tool is None: # 没有待确认的工具
            return ""

        if not confirmed: # 用户拒绝执行
            self.pending_tool = None
            self.messages.append({"role": "system", "content": "[User denied tool execution]"})
            return ""

        if not session_id:
            session_id = "default"
        if not user_id:
            user_id = "default"

        tool_registry = self._tool_registry()
        tools_spec = [t.to_openai_tool() for t in tool_registry.values()] if tool_registry else []

        tool_name = str(self.pending_tool.get("tool_name", ""))
        tool_args = dict(self.pending_tool.get("tool_args") or {})
        call_id = str(self.pending_tool.get("tool_call_id") or "")
        sig = str(self.pending_tool.get("sig") or "") or _tool_sig(tool_name, tool_args)
        self.pending_tool = None

        tool = tool_registry.get(tool_name) # 检查工具是否存在，如果不存在则在消息历史中添加错误信息
        if tool is None:
            self.messages.append(
                {
                    "role": "tool",
                    "name": tool_name or "unknown_tool",
                    "tool_call_id": call_id,
                    "content": json.dumps({"ok": False, "error": f"Unknown tool: {tool_name}"}, ensure_ascii=False),
                }
            )
        else:
            tool_args["confirmed"] = True
            try: # 执行工具
                result = tool.run(**tool_args)
                if sig:
                    self.executed_tool_sigs.add(sig)
                    self.tool_result_cache[sig] = result
            except Exception as e:
                result = json.dumps({"ok": False, "error": repr(e)}, ensure_ascii=False)

            self.messages.append({"role": "tool", "name": tool_name, "tool_call_id": call_id, "content": result})
            self.messages.append(
                {
                    "role": "system",
                    "content": f"[Tool executed] '{tool_name}:{call_id}' has been executed successfully.",
                }
            )

        final_text = ""
        for _ in range(max(1, int(self.max_steps))):
            system_prompt, user_prompt = self._build_prompts(
                user_id=user_id, session_id=session_id, instructions=instructions, subagent=False
            )
            model_msg = call_model(
                self.config.model_name,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                tools=tools_spec,
                tool_choice="auto" if tools_spec else "none",
            )

            assistant_text = str(model_msg.get("content") or "").strip()
            tool_calls = model_msg.get("tool_calls") or []

            if assistant_text:
                self.messages.append({"role": "assistant", "content": assistant_text})
                final_text = assistant_text

            if not tool_calls:
                break

            executed_any = False
            duplicate_only = True
            for call in tool_calls:
                tool_name2, tool_args2, call_id2 = self._parse_tool_call(call)
                if not tool_name2 or tool_name2 not in tool_registry:
                    self.messages.append(
                        {
                            "role": "tool",
                            "name": tool_name2 or "unknown_tool",
                            "tool_call_id": call_id2,
                            "content": json.dumps(
                                {"ok": False, "error": f"Unknown tool: {tool_name2}"},
                                ensure_ascii=False,
                            ),
                        }
                    )
                    continue

                tool2 = tool_registry[tool_name2]
                sig2 = _tool_sig(tool_name2, tool_args2)
                cached2 = self.tool_result_cache.get(sig2)
                if cached2 is not None:
                    self.messages.append({"role": "tool", "name": tool_name2, "tool_call_id": call_id2, "content": cached2})
                    continue
                try:
                    result2 = tool2.run(**tool_args2)
                    self.executed_tool_sigs.add(sig2)
                    self.tool_result_cache[sig2] = result2
                    executed_any = True
                    duplicate_only = False
                except PermissionError as e:
                    try:
                        payload2 = json.loads(str(e))
                    except Exception:
                        payload2 = {"decision": "confirm", "reason": str(e)}
                    self.pending_tool = {
                        "tool_name": tool_name2,
                        "tool_args": dict(tool_args2),
                        "tool_call_id": call_id2,
                        "sig": sig2,
                    }
                    payload2["tool"] = tool_name2
                    return json.dumps(payload2, ensure_ascii=False)
                except Exception as e:
                    result2 = json.dumps({"ok": False, "error": repr(e)}, ensure_ascii=False)
                    duplicate_only = False

                self.messages.append(
                    {"role": "tool", "name": tool_name2, "tool_call_id": call_id2, "content": result2}
                )
                if sig2:
                    self.messages.append(
                        {
                            "role": "system",
                            "content": f"[Tool executed] '{tool_name2}:{call_id2}' has been executed successfully.",
                        }
                    )

            if (not executed_any) and duplicate_only:
                self.messages.append(
                    {
                        "role": "system",
                        "content": "[Loop guard] Tools were repeatedly called with the same arguments and served from cache. Please provide the final answer without calling tools again.",
                    }
                )
                system_prompt3, user_prompt3 = self._build_prompts(
                    user_id=user_id, session_id=session_id, instructions=instructions, subagent=False
                )
                model_msg3 = call_model(
                    self.config.model_name,
                    system_prompt=system_prompt3,
                    user_prompt=user_prompt3,
                    tools=[],
                    tool_choice="none",
                )
                assistant_text3 = str(model_msg3.get("content") or "").strip()
                if assistant_text3:
                    self.messages.append({"role": "assistant", "content": assistant_text3})
                    final_text = assistant_text3
                break

        self.messages = self.context_manager.compact_messages(self.messages, user_id=user_id, session_id=session_id)
        from claude_agent.memory.auto_memory import AutoMemory
        from claude_agent.memory.session_memory import SessionMemory

        AutoMemory(storage_root=self.config.storage_dir, user_id=user_id).on_round_completed()
        AutoMemory(storage_root=self.config.storage_dir, user_id=user_id).schedule_write(
            [dict(role=str(m.get("role", "")), content=str(m.get("content", ""))) for m in self.messages],
            session_id=session_id,
            force=False,
        )
        SessionMemory(storage_root=self.config.storage_dir, user_id=user_id, session_id=session_id).schedule_write(
            [dict(role=str(m.get("role", "")), content=str(m.get("content", ""))) for m in self.messages]
        )
        return final_text or ""

    def _build_prompts(
        self, *, user_id: str, session_id: str, instructions: str, subagent: bool
    ) -> tuple[str, str]:
        '''构建提示词: 无环境信息、无记忆、无MCP，纯对话'''
        if subagent:
            # SubAgent模式：简化提示
            messages = [dict(role=str(m.get("role", "")), content=str(m.get("content", ""))) for m in self.messages]
            system_prompt = "You are a sub-agent.\n"
            user_prompt = "\n".join(f"{m.get('role','')}: {m.get('content','')}".strip() for m in messages)
            return system_prompt, user_prompt
        # 正常模式：使用PromptBuilder
        bundle = self.prompt_builder.build_prompts(
            user_id=user_id,
            session_id=session_id,
            messages=[dict(role=str(m.get("role", "")), content=str(m.get("content", ""))) for m in self.messages],
            instructions=instructions,
        )
        return bundle.system_prompt, bundle.user_prompt

    def _tool_registry(self) -> dict[str, BaseTool]:
        '''工具注册'''
        from claude_agent.tools.core_tools import (
            AgentTool,
            BashTool,
            FileEditTool,
            FileReadTool,
            FileWriteTool,
            GlobTool,
            GrepTool,
            SkillTool,
            TodoWriteTool,
            ToolSearchTool,
        )

        tools: list[BaseTool] = [
            BashTool(),
            FileReadTool(),
            FileWriteTool(),
            FileEditTool(),
            GlobTool(),
            GrepTool(),
            AgentTool(),
            TodoWriteTool(),
            ToolSearchTool(),
            SkillTool(),
        ]
        return {t.name: t for t in tools}

    def _parse_tool_call(self, call: Any) -> tuple[str, dict[str, Any], str]:
        '''解析OpenAI工具调用格式'''
        tool_name = ""
        args: dict[str, Any] = {}
        call_id = ""
        if isinstance(call, dict):
            call_id = str(call.get("id") or "")
            fn = call.get("function") or {}
            if isinstance(fn, dict):
                tool_name = str(fn.get("name") or "")
                raw_args = fn.get("arguments")
                if isinstance(raw_args, str):
                    try:
                        parsed = json.loads(raw_args)
                    except Exception:
                        parsed = {}
                    if isinstance(parsed, dict):
                        args = parsed
                elif isinstance(raw_args, dict):
                    args = dict(raw_args)
        return tool_name, args, call_id


if __name__ == "__main__":
    import os

    path = r"C:\Users\18415\Desktop"
    # 展开环境变量
    expanded_path = os.path.expandvars(path)
    print(expanded_path)
