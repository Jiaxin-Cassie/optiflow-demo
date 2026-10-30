# OptiFlow 公开 Demo 部署

我将公开 Demo 部署在 Streamlit Community Cloud，固定入口为 https://optiflow-cassie.streamlit.app/ ，源码为 https://github.com/Jiaxin-Cassie/optiflow-demo 。访客无需我的电脑开机即可访问。

2026-10-29 验证：未登录浏览器可以进入首页，完整走通业务确认、模型确认与云端真实求解，展示 A=100、B=200、利润 10000 的案例结果；应用无异常。本机不使用代理的 HTTPS 连接也返回 200。源码位于 https://github.com/Jiaxin-Cassie/optiflow-demo 。

保留当前 Streamlit V2 界面与四步流程、三类案例、自然语言补充数量限制、模型检查、真实求解、数值检查、版本对比和独立体验反馈。公开入口不需要邀请码，每个浏览器会话进入独立工作区；所有任务仍走原有服务与求解器，不使用静态结果代替计算。

## 当前云端配置

| 配置 | 当前值 |
| --- | --- |
| 仓库 | `Jiaxin-Cassie/optiflow-demo` |
| 分支 | `main` |
| 入口 | `resume_demo.py` |
| Python | 3.11 |
| 子域名 | `optiflow-cassie` |

发布时，我先生成清理后的源码包，再同步到这个独立仓库。发布包会清空配置中的本机密钥，排除 `.env`、运行数据库、口令、原始问卷及虚拟环境。

公开案例体验不需要 API Key。管理后台默认关闭；如果需要管理当前云实例的演示反馈，可以在 Streamlit Secrets 配置至少 16 位的 `OPTIFLOW_ADMIN_PASSWORD`，通过 `?admin=1` 进入登录页。该实例的数据与原受邀测试数据分开。

## 数据与能力边界

- 公开 Demo 仅启用内置案例，不消耗付费 LLM。自定义实时 Agent 和正式测试后台继续保留在原平台。
- 访客使用独立服务端作用域；不可列出别人的任务、问卷或管理数据。开始新的演示会建立新作用域。
- 演示数据库默认位于 `runtime/public_demo/tasks.sqlite3`，不能配置为正式测试数据库。部署包不包含原来的数据和密钥。
- 问卷功能保留；公开 Demo 记录标为 `public_demo`，不计入正式受邀研究。Community Cloud 本地文件不能作为可靠的长期调研存储，重启或重新部署可能丢失演示记录。需要长期保留的正式调研继续使用现有专属测试服务，或另接持久数据库。
- 免费 Community Cloud 无访问 12 小时会休眠，访客可以唤醒；固定地址不等于始终免等待。官方说明：https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app

## 本地预览与打包

```powershell
.venv-workbench/Scripts/python.exe run_experiment.py --public-demo --workbench-port 8502
.venv-workbench/Scripts/python.exe run_experiment.py --package-demo dist/OptiFlow-resume-demo.zip
.venv-workbench/Scripts/python.exe run_experiment.py --method all --dry_run
```

Streamlit Cloud 直接运行 `resume_demo.py`。本地及容器通过统一入口 `run_experiment.py --public-demo` 启动。我在发布后使用未登录浏览器检查业务确认、模型确认和真实求解流程。
