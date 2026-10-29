# 技术架构与代码职责

## 目录职责

| 目录 / 模块 | 职责 |
| --- | --- |
| `run_experiment.py`、`src/workbench/cli.py` | 本地入口、后台工作进程、检查与交付打包 |
| `resume_demo.py`、`public_demo.py` | 云端公开入口、访客作用域、内置案例范围和计算准入 |
| `app.py`、`workspace_ui.py`、`theme.py` | 页面装配、四阶段导航、独立体验问卷和统一样式 |
| `service.py`、`flow.py` | 创建、建模、版本修订、两次确认和求解状态检查 |
| `adapter.py`、`src/agents/` | 复用需求解析、技能路由、建模、代码审阅与调试能力 |
| `src/llm_client.py`、`src/prompts.py` | 集中模型调用与提示词管理 |
| `model.py`、`solver.py`、`src/agents/evaluator.py` | 模型结构检查、受控求解、独立进程和数值重算 |
| `explanations.py`、`review.py`、`review_ui.py`、`charts.py` | 业务解释、原文对照、变更说明、结果与数量图 |
| `store.py`、`hosting.py`、`usability.py` | SQLite 快照与事件、任务归属、邀请、问卷和导出 |
| `manual_study.py`、`manual_ui.py` | 兼容历史六任务协议，不改写旧测试数据 |
| `tests/` | 服务契约、权限隔离、真实求解、版本、UI 及发布包检查 |

## 两种建模来源，共用后续接口

内置案例由 `cases.py` 读取标注模型，明确不调用实时 LLM；实时模式由 `AgentAdapter` 调用原建模能力。两种来源都经过统一模型校验、业务确认、模型确认、受控求解和数值检查。

核心服务入口为 `create_task`、`prepare_task`、`revise_task`、`confirm_task` 和 `solve_task`。业务确认由 `confirm_business` 保存，不由页面浏览或体验反馈代替。

## 状态与依赖

```text
pending → modeling → awaiting_confirmation
                         │ 业务确认 + 模型确认
                         ↓
                     solving → executing
                                  ↓
                      completed / no_solution / needs_attention

阶段失败 → failed（保存失败阶段和错误分类）
需求修改 → revising → modeling → 当前版本重新确认
```

`TaskStore.claim` 使用 SQLite 写事务认领阶段，检查状态、期望版本和业务确认。求解前再次核对确认指纹。修订归档旧模型、旧确认与旧结果，清空当前依赖项。

## 执行和验证边界

LLM 生成代码只供审阅。实际运行的入口由平台可信代码生成，读取经确认的数据模型，调用 CVXPY / SciPy / HiGHS；不执行用户或 LLM 提供的任意 Python 表达式。

独立进程有运行时间预算。求解完成后独立重算约束、边界、整数性与目标值。该机制不是通用公开代码执行沙箱，也不构成业务语义证明。

## 数据和公开访问

正式测试保存在自己的数据库；公开 Demo 使用单独路径及访客作用域。参与者的读取、保存、事件和阶段认领都经过归属检查。管理员统一导出需要单独登录，公开访客不能进入全量数据视图。

SQLite 适用于当前单实例验证。多个副本共享写入、长期调研存储、账号体系与生产级资源隔离需要后续工程设计，不在当前实现中隐含承诺。
