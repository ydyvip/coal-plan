"""自定义 AutoGen 组件：ToolAgent —— 把一个“专业工具”包装成可序列化的 BaseChatAgent。
序列化后 provider 为 `app.agents.ToolAgent`，可被 `ComponentLoader.load_component` 还原。"""
from __future__ import annotations
import time
from contextvars import ContextVar
from pydantic import BaseModel
from autogen_core import Component, CancellationToken
from autogen_agentchat.agents import BaseChatAgent
from autogen_agentchat.base import Response
from autogen_agentchat.messages import TextMessage
from .tools import TOOLS, RunContext

CURRENT_RUN: ContextVar[RunContext | None] = ContextVar("CURRENT_RUN", default=None)
_FALLBACK: dict = {"ctx": None}   # 若 contextvar 未传播到 runtime 任务，则回退（见 README 常见问题）


def current_ctx() -> RunContext:
    ctx = CURRENT_RUN.get() or _FALLBACK["ctx"]
    if ctx is None:
        raise RuntimeError("ToolAgent 必须在 RunContext 内执行")
    return ctx


class ToolAgentConfig(BaseModel):
    name: str
    description: str = ""
    tool: str
    params: dict = {}


class ToolAgent(BaseChatAgent, Component[ToolAgentConfig]):
    component_config_schema = ToolAgentConfig
    component_provider_override = "app.agents.ToolAgent"

    def __init__(self, name: str, description: str = "", tool: str = "plan_task", params: dict | None = None):
        super().__init__(name, description)
        if tool not in TOOLS:
            raise ValueError(f"未知专业工具: {tool}")
        self.tool = tool
        self.params = params or {}

    @property
    def produced_message_types(self):
        return (TextMessage,)

    async def on_messages(self, messages, cancellation_token: CancellationToken) -> Response:
        ctx = current_ctx(); spec = TOOLS[self.tool]
        full = {p["key"]: p["default"] for p in spec.params} | self.params
        ctx.current_agent = self.name
        t0 = time.perf_counter()
        ctx.emit("agent_start", agent=self.name, tool=self.tool, label=spec.label, params=full,
                 requires=spec.requires, provides=spec.provides)
        try:
            text = spec.fn(ctx, full)          # 同步、无 await：并行分支不会交错写 current_agent
        except Exception as e:                  # noqa
            ctx.emit("agent_end", agent=self.name, ok=False, error=str(e), seconds=round(time.perf_counter() - t0, 4))
            raise
        dt = round(time.perf_counter() - t0, 4)
        ctx.emit("tool_call", agent=self.name, tool=self.tool, params=full, seconds=dt,
                 provides=spec.provides, summary=text[:300])
        ctx.emit("agent_end", agent=self.name, ok=True, seconds=dt)
        return Response(chat_message=TextMessage(content=f"【{spec.label}】{text}", source=self.name))

    async def on_reset(self, cancellation_token: CancellationToken) -> None:
        return None

    def _to_config(self) -> ToolAgentConfig:
        return ToolAgentConfig(name=self.name, description=self.description, tool=self.tool, params=self.params)

    @classmethod
    def _from_config(cls, config: ToolAgentConfig) -> "ToolAgent":
        return cls(config.name, config.description, config.tool, config.params)
