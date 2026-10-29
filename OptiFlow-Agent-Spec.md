# OptiFlow · 能力与任务协议

版本 v1.1；适用于当前可运行平台，更新于 2026-10-28。

2026-10-29 P0 补充：`explanations.py` 仅从现有模型和结果生成业务视图，不调用模型服务；`usability.py` 在同一 SQLite 中保存匿名测试会话并复用事件表。人工确认、指纹与求解协议保持不变。

在线测试扩展：`hosting.py` 保存邀请令牌哈希并在服务端限定参与者可访问的任务；`hosting_ui.py` 提供管理员口令入口、批量邀请和全量导出。启动参数 `--study-server` 启用隔离模式，普通本机模式保持原有入口。部署采用单实例与持久数据卷，状态不放在参与者浏览器中。详见 [在线部署](docs/ONLINE-STUDY.md)。

新增表：`usability_tests`（匿名编号、案例、开始与结束、人工判定标准及问卷）、`usability_event_keys`（跨 rerun / 重连去重）。每个视图事件按测试 ID、事件名、模型版本只记录一次；确认与反馈事件在原任务保存事务中同步记录。新增事件不重复保存业务原文。

审核时间口径：首次打开模型确认页，到首次有效确认；未确认但已结束时取结束时间。未进入审核或仍在审核的记录不填 0。完成必须由参与者显式标记且当前结果有效、已被查看；问卷可随后提交或跳过。错误发现率仅统计有预定义标准且人工已评定的记录。

删除仅作用于一条专用测试任务及其问卷、事件、trace、代码和日志；后台处理未结束时禁止删除，普通任务不受影响。

## 1. 分层架构

```text
run_experiment.py / 启动工作台.cmd
  └─ Streamlit：工作台总览、任务、流程、模型、结果、记录、技能库、能力说明
      ├─ 任务服务：创建 → 建模 → 等待确认 → 求解 → 验证
      ├─ 后台作业：独立本地 Python 进程，SQLite 持久化进度
      └─ 建模能力
          ├─ 需求解析 Agent
          ├─ 技能检索 / 筛选 Agent
          ├─ Formulation Agent → 标准五要素模型
          ├─ 数据适配 → 严格 LP / MILP JSON
          ├─ Code Agent / Debugger → 仅供审阅的代码
          └─ 可信模型解释器 → CVXPY / HiGHS → 独立数值检查
```

所有模型服务调用经 `src/llm_client.py`，提示词集中在 `src/prompts.py`，连接配置集中在 `src/config.py`。没有独立的科研实验运行链路。

## 2. 各阶段的输入输出

| 阶段 | 输入 | 输出 | 失败处理 |
| --- | --- | --- | --- |
| 需求解析 | 原文与历次用户补充 | 目标、实体、参数、业务关系、歧义 | 标记解析失败，不使用虚构事实 |
| 技能检索 | 需求要素、当前技能库 | 候选、激活条目、选择依据 | 记录规则降级或检索失败 |
| 数学建模 | 原文、要素、相关知识 | 五要素模型、严格线性 JSON、原文引用 | 不合规或不支持则失败 |
| 人工确认 | 模型版本、假设与缺失信息 | 绑定模型指纹的确认记录 | 缺失输入、重复或旧版本确认被阻止 |
| 代码生成 | 已确认 JSON、求解知识 | 审阅代码；语法问题可修复一次 | 不执行任意生成 Python |
| 执行修复 | 已确认模型数据 | 求解器状态、目标值、决策量、耗时 | 独立进程超时和求解失败被记录 |
| 结果校验 | 模型、决策量、目标值 | 约束、边界、整数性、目标重算 | 返回完整明细，不直接宣称语义正确 |

五要素模型是标准中间表示，产品差异化是模型确认、反馈修订和验证闭环。

## 3. 模型数据协议

```json
{
  "kind": "MILP",
  "variables": [
    {"name": "A", "label": "产品 A 产量", "unit": "件", "domain": "integer",
     "lower": 0, "upper": null, "source": "产量为非负整数。"}
  ],
  "objective": {
    "label": "总利润", "unit": "元", "sense": "max",
    "coefficients": {"A": 40}, "constant": 0,
    "source": "A 每件利润 40 元。"
  },
  "constraints": [
    {"id": "capacity", "label": "产量限制", "coefficients": {"A": 1},
     "relation": "<=", "rhs": 100, "source": "A 最多生产 100 件。"}
  ],
  "assumptions": [], "missing_inputs": []
}
```

这里是协议示例，系数不代表任何已提交任务。变量最多 200 个、约束最多 1000 条；系数须为有限数值且绝对值不超过 1e12。变量名唯一，关系仅接受 `<=`、`>=`、`==`。不使用 eval 或表达式字符串执行模型。

`source` 必须是需求原文的连续子串，或显式提供待确认假设。引用存在不证明系数与语义转换正确，仍需确认页检查。

## 4. 生命周期与一致性

```text
pending → modeling → awaiting_confirmation
awaiting_confirmation → solving → executing → completed / no_solution / needs_attention / failed
已建模的可编辑任务 → revising → modeling → awaiting_confirmation
```

修订保留旧模型、结果和确认记录，清空当前模型与结果，并撤销确认。确认绑定版本号和 SHA-256 模型指纹。SQLite 事务保护确认和执行的状态迁移，防止重复作业与过期操作。

`completed` 表示 Optimal 且数值检查通过；`no_solution` 用于不可行、无界等状态；`needs_attention` 表示非最优或需要复核；`failed` 表示某阶段失败。Badcase 处理状态独立于以上结果。

## 5. 检索、求解与用量

- 技能库保留实际可用的 50 个建模条目，按任务类型、建模技巧和求解实现组织。目录包含使用条件、规则、边界与来源。
- 采用业务词映射与词项相似度召回，可调用模型进一步选择。该方式是产品当前实现，不宣称经过对照评测或达到最优检索效果。
- 所有 LP / MILP 实际求解通过 CVXPY 的 SCIPY / HiGHS 后端。整数域不交给不支持整数规划的求解器。
- 求解器预算 15 秒，进程总预算 30 秒；这不等于操作系统级资源沙箱。
- 数值检查独立重算约束、边界、整数 / 二元域和目标值。线性检查使用 `1e-5 * max(1, abs(lhs), abs(rhs))`；整数性使用绝对容差。
- 调用次数、token 与 API 延迟从统一客户端记录；未返回实际用量时明确标为估算。未配置价格时不生成费用数字。

## 6. 存储与安全边界

运行数据位于 `runtime/`，包含 SQLite、任务 trace、工作进程日志与求解入口。源码包不附带历史任务、旧数据集或密钥。

本机平台仅监听 `127.0.0.1`，不自动发布。公开部署前需要用户认证、数据隔离、作业治理、资源限制及系统级文件和网络策略。API 密钥不显示在页面，也不输出到报告和错误。

## 7. 任务 API

```python
from src.workbench.service import run_optimization_task, confirm_task, revise_task

task = run_optimization_task(problem_text, selected_skills=None)
# 模型就绪后等待用户检查，不自动确认。
solved = confirm_task(task["task_id"], expected_version=task["model_version"])
revised = revise_task(solved["task_id"], "产品 A 的产量不能超过 80 件。",
                      expected_version=solved["model_version"])
# revised 需要再次确认。
```

`None` 自动检索，名称列表限定候选范围，空列表不注入技能。各能力均可通过主入口的 CLI 使用，见 [部署与运行](DEPLOY-GUIDE.md)。

