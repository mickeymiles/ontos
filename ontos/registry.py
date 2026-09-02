"""本体元素注册表基座。

P0 仅提供"声明 + 实现绑定 + call 委托"的最小能力，不引入行为变化。
P1 起：Function/Action/Skill 的 impl 在 adapter 阶段委托现有 etl.py/project_metrics.py，
随后逐步替换为受治理实现（validate_action / 审计 / S1–S5）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class Definition:
    """本体元素的语义声明（来自文件，非代码内联）。"""
    id: str
    name: str
    kind: str                      # "function" | "action" | "skill"
    domain: str = ""              # 业务域：financial / procurement / project ...
    description: str = ""
    inputs: list = field(default_factory=list)
    outputs: list = field(default_factory=list)
    invariant: Optional[str] = None   # 不变量（校验器用）
    version: str = "0.1"
    ontology_bound: bool = True        # False = 通用旁路工具，不经 9010 / 不受 S1-S5
    employee_bound: bool = False       # Skill 是否绑定 Employee（Q10）
    meta: dict = field(default_factory=dict)


class RegistryError(Exception):
    """注册/调用失败。"""


class GenericRegistry:
    """通用注册表：声明存 _defs，实现存 _impls；call 委托给 impl。"""

    def __init__(self, kind: str):
        self.kind = kind
        self._defs: dict[str, Definition] = {}
        self._impls: dict[str, Callable[..., Any]] = {}

    # ---- 注册 ----
    def register(self, definition: Definition, impl: Optional[Callable[..., Any]] = None) -> None:
        if definition.kind != self.kind:
            raise RegistryError(
                f"类型不匹配：定义 {definition.id} 为 {definition.kind}，注册表为 {self.kind}"
            )
        self._defs[definition.id] = definition
        if impl is not None:
            self._impls[definition.id] = impl

    def get(self, id: str) -> Definition:
        if id not in self._defs:
            raise RegistryError(f"{self.kind} [{id}] 未注册")
        return self._defs[id]

    def has(self, id: str) -> bool:
        return id in self._defs

    # ---- 执行 ----
    def call(self, id: str, **kwargs: Any) -> Any:
        """默认委托给已注册 impl（adapter 阶段 impl 即现有函数）。

        后续阶段可在此插入：不变量校验、审计、S1–S5 写权限判定。
        """
        if id not in self._impls:
            raise RegistryError(f"{self.kind} [{id}] 已声明但无实现（adapter 未绑定）")
        return self._impls[id](**kwargs)

    def ids(self) -> list[str]:
        return list(self._defs)


class FunctionRegistry(GenericRegistry):
    def __init__(self):
        super().__init__("function")


class ActionRegistry(GenericRegistry):
    def __init__(self):
        super().__init__("action")


class SkillRegistry(GenericRegistry):
    def __init__(self):
        super().__init__("skill")


# 平台与智能体共享的单例（同一进程内唯一真相）
functions = FunctionRegistry()
actions = ActionRegistry()
skills = SkillRegistry()
