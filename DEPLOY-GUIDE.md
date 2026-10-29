# OptiFlow · 启动、配置与交付

异地参与者请使用在线测试部署模式，而不是各自在电脑启动独立项目。现已提供 `--study-server`、管理员后台、专属邀请、共享数据卷及 Docker / HTTPS 配置；步骤与尚未验证范围见 [在线测试部署](docs/ONLINE-STUDY.md)。普通本机模式继续保留。

## 本机启动

双击 `启动工作台.cmd` 或 `start-local.bat`。当前机器已配置 `.venv-workbench`：

```powershell
.venv-workbench/Scripts/python.exe run_experiment.py --workbench
```

在浏览器访问 [本地工作台](http://127.0.0.1:8501)。运行 `python run_experiment.py` 也会默认启动平台。若端口被占用，使用 `--workbench-port 8502`。

## 新机器安装

推荐 Python 3.10–3.12：

```powershell
python -m venv .venv-workbench
.venv-workbench/Scripts/python.exe -m pip install -r requirements.txt
.venv-workbench/Scripts/python.exe run_experiment.py
```

虚拟环境和运行数据库不能直接复制到其他机器；独立源码包中不包含它们。

## 配置模型服务

模型配置统一从 `src/config.py` 读取。源码交付包会清空本机已有的密钥默认值。使用前在进程环境配置供应商密钥、兼容地址与模型名；变量示例见 `.env.example`。当前代码读取进程环境，不会自动加载 `.env` 文件。

内置业务案例无需 API 即可使用。实时建模会实际调用模型服务，按供应商规则产生用量。页面记录调用数与 token，缺失用量时标明估算，不假装显示账单费用。

## 任务 CLI

```powershell
# 建立内置案例，停在模型确认前
python run_experiment.py --workbench-case production

# 查看任务，再明确确认当前版本
python run_experiment.py --workbench-task TASK_ID
python run_experiment.py --workbench-task TASK_ID --workbench-confirm-business 1
python run_experiment.py --workbench-task TASK_ID --workbench-confirm 1

# 补充条件会生成新版本，需要再次确认
python run_experiment.py --workbench-task TASK_ID --workbench-feedback "A <= 80" --workbench-version 1
python run_experiment.py --workbench-task TASK_ID --workbench-confirm-business 2
python run_experiment.py --workbench-task TASK_ID --workbench-confirm 2 --workbench-report decision-report.md

# 自定义 UTF-8 业务需求文件，调用实时建模服务
python run_experiment.py --workbench-problem problem.txt
```

可以通过 `--workbench-db PATH` 使用独立任务库。默认运行数据在 `runtime/`；不要把用户任务数据库打包到公开作品集。

## 验证与打包

```powershell
python run_experiment.py --workbench-test
python run_experiment.py --smoke-test
python run_experiment.py --package dist/OptiFlow-platform.zip
```

旧检查命令 `--method all --dry_run` 作为兼容别名保留，现执行三个业务案例的本机求解检查；它不再运行科研基线。检查只使用自己创建的临时数据库，确认动作用于开发验收。

打包使用显式文件清单，只包含平台源码、实际使用的技能目录、文档与截图。排除旧实验、原始数据、模型缓存、API 日志、环境文件、运行记录和虚拟环境；密钥默认值会被清空。

已补充面向小规模研究的共享在线服务部署配置，但没有实际开通公网环境。企业级多租户、账号系统、持久作业队列与自动恢复仍未实现。

