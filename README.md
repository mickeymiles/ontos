# ontos — 本体引擎统一库（独立仓）

> 本体智能体平台的**单一真相源**引擎库。被 `neuops-agent-demo`(9007) 与 `contract-compare-9006`(9006) 以 git submodule 引用，消除两仓 `app/ontology/` 与 `backend/ontology_engine/` 的逐字副本漂移。

## 设计原则（对应四元关系模型与改造计划）

1. **声明与实现分离**：`Definition`（语义：inputs/outputs/不变量/版本/责任人）来自文件(YAML/JSON)；`impl`（可执行 Python）来自代码。注册表是"语义↔实现"的桥。
2. **双真相源禁止**：本仓只存定义 + 实现；**DB 仅存授权/绑定**（`employee_skill` / `skill_mcp`），不存定义本身（Q7=桥接）。
3. **Skill 绑定 Employee**（Q10=是）：Skill 是数字员工的能力边界，`employee_bound` 标记 + DB `employee_skills` 控制可见/启用。
4. **Tool 分两类**：`ontology_bound=True` 为领域工具（受 S1–S5/审计/经 9010）；`False` 为通用旁路工具（HTML/PDF/Excel/代码，不经 9010、不改事实栏）。
5. **绞杀者模式**：本仓与旧 `app/ontology/` 并行；旧 import 经 compat shim 指向本仓；行为变更一律走特性开关，可回退。

## 注册表

| 注册表 | 元素 | 调用方 |
|---|---|---|
| `FunctionRegistry` | Function（判定/计算/约束，只读） | 平台页 handler、Skill 查数 |
| `ActionRegistry` | Action（受约束的写回） | 平台按钮、Skill 触发 |
| `SkillRegistry` | Skill（编排包，LLM 唯一可见） | 智能体 loader |

`call(id, **kwargs)` 默认委托给已注册 `impl`（P1 adapter 阶段 impl 即现有 `etl.py`/`project_metrics.py` 函数，**零行为变化**）。

## 特性开关（部署侧 env，默认 0=旧逻辑）

- `ONT_USE_ONTOS` — 平台/智能体是否启用本仓（替换旧 ontology 模块）
- `ONT_LLM_DECISION` — 运行时是否走 LLM 决策（否则硬编码状态机）
- `ONT_PLATFORM_REGISTRY` — 页面 handler 是否改调 FunctionRegistry
- `ONT_AGENT_SKILL_MODE` — 智能体是否改走 Skill 级暴露（Q8）

## 目录

```
ontos/
  __init__.py
  registry.py        # Function/Action/Skill 三注册表基座
  compat/            # 9007/9006 的兼容 shim（旧 import → 本仓）
  functions/         # Function 实现（从 etl/project_metrics 收敛）
  actions/           # Action 实现（经 validate_action + 审计）
  skills/            # Skill 定义文件（YAML/JSON，真相源）
```
