# OptiFlow 简历公开 Demo

已部署固定入口：https://optiflow-cassie.streamlit.app/

2026-10-29 验证：未登录浏览器可以进入首页，完整走通业务确认、模型确认与云端真实求解，展示 A=100、B=200、利润 10000 的案例结果；应用无异常。本机不使用代理的 HTTPS 连接也返回 200。源码位于 https://github.com/Jiaxin-Cassie/optiflow-demo 。

保留当前 Streamlit V2 界面与四步流程、三类案例、自然语言补充数量限制、模型检查、真实求解、数值检查、版本对比和独立体验反馈。公开入口不需要邀请码，每个浏览器会话进入独立工作区；所有任务仍走原有服务与求解器，不使用静态结果代替计算。

## Streamlit Community Cloud 设置

1. 将**清理后的简历部署包**解压到独立 GitHub 仓库根目录。不要上传本机原目录中的 `src/config.py`、`.env`、`runtime`、口令、用户问卷或虚拟环境。
2. 在 https://share.streamlit.io 登录并授权该代码仓库，选择 Create app。
3. Repository 选择新仓库；Branch 选择实际上传分支；Main file path 填 `resume_demo.py`。
4. Advanced settings 选择 Python 3.11。App URL 选择一个可用子域名，例如 `optiflow-cassie`；名称只是建议，部署平台确认可用并成功上线后才是实际地址。
5. 公开案例体验不需要 API Key。默认不启用管理后台。如需查看此实例的演示反馈，在 Streamlit Secrets 设置至少 16 位的 `OPTIFLOW_ADMIN_PASSWORD`；通过固定地址加 `?admin=1` 登录。
6. 部署成功后，用未登录或无痕浏览器完成一次“案例 → 确认业务规则 → 确认模型 → 求解 → 补充数量上限 → 重新确认与计算 → 体验反馈”，再将平台返回的真实地址写入简历。

GitHub Copilot Space 是资料工作区，不能作为 Streamlit 的 Repository；需要普通代码仓库网址，格式为 `https://github.com/账号/仓库名`。

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

Streamlit Cloud 直接运行 `resume_demo.py`。本地及容器仍可通过统一入口 `run_experiment.py --public-demo` 启动。简历链接必须以部署平台成功返回的 URL 为准，不能把建议子域名或临时隧道当作已经上线的固定链接。
