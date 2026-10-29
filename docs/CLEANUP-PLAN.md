# OptiFlow · 旧项目清理记录

状态：已获用户明确确认并完成清理，共处理 76 个清单目标。逐项记录见 `CLEANUP-MANIFEST.json`；父目录中已包含的缓存目标计入清单，因此不是 76 个独立顶层目录。

当前平台已解除对以下模块的依赖。独立源码交付包采用白名单，不包含本清单内的旧数据与旧代码。

## 已删除的目录

| 路径 | 内容 | 对新平台的影响 |
| --- | --- | --- |
| `analysis/`、`configs/` | 旧统计与实验配置 | 无运行依赖 |
| `data/` | 原研究数据集、标签、历史贡献数据 | 模板已内置，平台不再读取 |
| `experiments/`、`KnowledgeVerification/` | 对照实验、研究协议、核验与备份 | 已解除全部产品导入依赖 |
| `models/` | 研究用本地向量模型缓存 | 现采用轻量业务词检索 |
| `outputs/`、`results/` | 旧实验结果、API trace、归档、旧版本测试任务 | 新任务存入 runtime；展示截图已移至 docs/assets |
| `scripts/` | 数据转换与学术绘图脚本 | 不属于平台运行链路 |
| `参考文献/` | 论文、研究汇报等资料 | 不属于产品交付 |
| `src/baselines/` | 旧对照基线 | 已由产品统一任务入口替代 |
| `.validation_dependencies/`、`.test_tmp/`、`.ruff_cache/`、`.venv/` | 旧检查依赖、临时文件与未使用环境 | 保留实际在用的 .venv-workbench |

## 已删除的独立文件

- 根目录：`2026_EMNLP_ROME (5.20)(1).pdf`、`实验说明.md`、`requirements-py39.txt`、`requirements-rq-optional.txt`、`gurobi.log`、`model.ilp`。
- 旧研究模块：`src/conditional_k2_router.py`、`src/moe_dynamic_routing.py`、`src/evidence.py`、`src/failure_trace.py`、`src/independent_evaluation.py`、`src/experiment_records.py`、`src/result_classification.py`、`src/text_similarity.py`、`src/rule_dictionary.py`。
- 旧页面适配：`src/workbench/history.py`。界面和测试已不再引用它。
- `docs/` 下旧研究和旧版产品文档：保留 `assets/`、本文件与 `VALIDATION.md`，其余旧文档删除，新 PRD、能力说明与演示指南统一放在根目录。
- 工作区内的 `__pycache__/` 和根目录 `.chart-data-*`：生成缓存，可随时重建。

## 明确保留

保留新平台源码、`skill_library/knowledge.json` 实际技能库、产品文档与截图、启动器、依赖说明、`src/config.py`、本机 `.env`、`.venv-workbench`、编辑器配置与 Git 元数据。技能库内保留实际知识条目，删除其 archive、reviews、旧版本快照和研究扩展。

参考项目 `D:\实习作品\visionagent-coze-proxy-main` 仅读取，清理不会触碰它。

以上原始数据、历史结果和论文资料已按确认范围永久删除。Python 和界面运行时可能重新生成缓存；新任务存储在 runtime，不属于旧实验残留。
