"""ontos — 本体引擎统一库。

单真相源：声明(Definition)来自文件，实现(impl)来自 Python；
DB 仅存授权/绑定（不存定义）。平台与智能体共享同一份注册表。
"""
from .registry import (
    Definition,
    RegistryError,
    GenericRegistry,
    FunctionRegistry,
    ActionRegistry,
    SkillRegistry,
    functions,
    actions,
    skills,
)

__all__ = [
    "Definition",
    "RegistryError",
    "GenericRegistry",
    "FunctionRegistry",
    "ActionRegistry",
    "SkillRegistry",
    "functions",
    "actions",
    "skills",
]
