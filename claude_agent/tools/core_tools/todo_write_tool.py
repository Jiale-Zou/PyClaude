from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

from claude_agent.tools.base_tool import BaseTool


class ScheduledTask(BaseModel):
    task_id: str # 任务的唯一标识符，创建实例时必须提供此字段。
    run_at: str # 任务计划执行的时间，预期为 ISO 8601 格式字符串
    payload: dict[str, Any] = Field(default_factory=dict) # payload 字段可以存储任意附加数据
    executed: bool = False # executed 标记任务是否已执行过


class TodoWriteInput(BaseModel):
    '''定义工具的输入模型。所有传给 execute 的参数都会先被这个模型校验'''
    action: Literal["add", "list", "remove", "clear", "run_due"]
    user_id: str = "default" # 用户标识，用于隔离不同用户的任务数据。
    task: ScheduledTask | None = None # 任务对象，仅在 action="add" 时需要。
    task_id: str | None = None # 任务ID，仅在 action="remove" 时需要。
    now: str | None = None # 当前时间字符串，仅在 action="run_due" 时可能用到。


class TodoWriteOutput(BaseModel):
    '''定义工具的输出模型。execute 方法最终必须返回此模型的实例'''
    action: str # 本次执行的操作类型，直接回显输入中的 action
    user_id: str # 本次操作涉及的用户ID
    tasks: list[ScheduledTask] = Field(default_factory=list) # 操作完成后，该用户的完整任务列表
    due: list[ScheduledTask] = Field(default_factory=list) # 仅在 action="run_due" 时有值，包含本次触发执行的到期任务列表

# 作为简易内存数据库。它按用户ID隔离数据，每个用户拥有一个独立的 {任务ID: 任务对象} 字典
_TASKS_BY_USER: dict[str, dict[str, ScheduledTask]] = {}


@dataclass(slots=True)
class TodoWriteTool(BaseTool):
    name: str = "todo_write"
    search_hint: str = "维护可调度的任务清单与到期检查，适合后台定时执行流程"
    description: str = "Maintain a structured todo list."
    input_schema = TodoWriteInput #  BaseTool.run 方法会使用它来校验输入参数
    output_schema = TodoWriteOutput
    needs_permission: bool = False

    def _parse_time(self, value: str) -> datetime:
        ''' 这是一个内部方法，用于将字符串转为带时区信息的 datetime 对象'''
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    def execute(self, **kwargs: Any) -> BaseModel:
        action = str(kwargs["action"]) # 从关键字参数中提取 action，并确保为字符串类型
        user_id = str(kwargs.get("user_id", "default")) # 提取 user_id，若未提供则使用默认值 "default"
        tasks = _TASKS_BY_USER.setdefault(user_id, {}) # setdefault 方法：若 user_id 键不存在，则创建一个空字典并返回；若已存在，则直接返回对应的字典

        if action == "add":
            task = kwargs.get("task")
            if task is None:
                return TodoWriteOutput(action=action, user_id=user_id, tasks=list(tasks.values()))
            tasks[task["task_id"]] = ScheduledTask(**task) # 将任务字典转换为 ScheduledTask 实例并存入_TASKS_BY_USER
            return TodoWriteOutput(action=action, user_id=user_id, tasks=list(tasks.values()))

        if action == "remove":
            task_id = str(kwargs.get("task_id") or "") # 获取要移除的 task_id，若不存在则使用空字符串
            tasks.pop(task_id, None)
            return TodoWriteOutput(action=action, user_id=user_id, tasks=list(tasks.values()))

        if action == "clear":
            tasks.clear() # 清空当前用户的任务字典
            return TodoWriteOutput(action=action, user_id=user_id, tasks=[])

        if action == "run_due":
            now_str = kwargs.get("now") # 获取传入的 now 参数并使用_parse_time解析时间；若未传入，则获取系统当前 UTC 时间
            now = self._parse_time(str(now_str)) if now_str else datetime.now(timezone.utc)
            due: list[ScheduledTask] = [] # 初始化一个列表，用于存放本次检查到的到期任务
            for task in tasks.values():
                if task.executed: # 如果任务已经被标记为执行过，则跳过
                    continue
                if self._parse_time(task.run_at) <= now: # 如果任务时间 <= 当前时间，说明该任务已到期
                    due.append(task)
            for task in due: # 遍历所有到期任务，使用 model_copy 方法创建一个任务副本，并将 executed 更新为 True，这样做不会修改原对象
                tasks[task.task_id] = task.model_copy(update={"executed": True})
            return TodoWriteOutput(action=action, user_id=user_id, tasks=list(tasks.values()), due=due)

        return TodoWriteOutput(action=action, user_id=user_id, tasks=list(tasks.values()))
