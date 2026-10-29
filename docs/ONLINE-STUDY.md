# 异地参与者与管理员统一导出

本版具备可部署代码与容器配置。只有 Windows 电脑时，可先用 [Windows 临时外网入口](WINDOWS-SHARE.md)，无需另购服务器；下文主要说明固定域名和长期服务器部署。

## 数据到底存在哪里

部署后，参与者在不同地方使用浏览器访问**同一个服务地址**，任务、操作事件和问卷都会写入服务器同一份 SQLite 数据库。不是保存在参与者的浏览器里，也不需要每个人把 CSV 发给组织者。

参与者持有不同的专属邀请链接，只能运行自己被分配的内置案例，不能查看其他人的任务、全量汇总或管理员操作。你使用管理员口令进入后台，统一导出全部已开始测试的记录。普通受邀人员不需要账号和密码。

SQLite 保存在挂载的数据卷内，应用容器替换与重启不应丢失已提交记录。邀请、任务和问卷均在同一数据库。当前设计为**一个服务实例 + 一份持久数据卷**，不用于多副本部署；仅将代码放到静态网站托管上不能运行本项目的 Python 求解进程。

## 上线需要什么

- 一台可运行 Docker Compose 的 Linux 服务环境。
- 一个解析到该环境的域名，允许访问 TCP 80 / 443。
- 一份至少 16 位的管理员口令和持久化数据卷。

不需要为参与者配置 LLM Key：在线受邀测试限定三个已有内置案例，求解仍是真实执行。普通本机模式保留原有实时建模能力。

## 现在先在本机体验后台

当前电脑可以在 PowerShell 中运行下面的命令。口令交互输入，不写入命令历史；这仍是本机预览，不能发给异地参与者：

```powershell
$studyPassword = Read-Host '设置本次后台口令（至少16位）' -AsSecureString
$env:OPTIFLOW_ADMIN_PASSWORD = [System.Net.NetworkCredential]::new('', $studyPassword).Password
$env:OPTIFLOW_PUBLIC_URL = 'http://127.0.0.1:8501'
.venv-workbench/Scripts/python.exe run_experiment.py --study-server
```

随后打开 `http://127.0.0.1:8501/?admin=1` 登录，在“参与者邀请”创建链接，在“全量数据与导出”提取记录。结束后关闭该 PowerShell 窗口即可清除本次进程环境中的口令。

## 部署步骤

1. 解压交付包到服务目录，安装 Docker Engine / Compose。安装方式按 [Docker 官方说明](https://docs.docker.com/engine/install/)选择系统版本。
2. 在目录内生成经过凭据清理的构建源包：

   ```sh
   python3 run_experiment.py --package dist/OptiFlow-platform.zip
   ```

   此命令需要 Python 3.10+，无需先安装求解依赖。Docker 构建只接收这个干净包及 requirements.txt，不复制本机 .env、src/config.py、runtime 或虚拟环境到构建上下文。
3. 将 `deploy.env.example` 复制为 `deploy.env`，在本机编辑三个值：

   ```dotenv
   OPTIFLOW_ADMIN_PASSWORD=填写你自己的长随机口令
   OPTIFLOW_PUBLIC_URL=https://你的实际域名
   OPTIFLOW_DOMAIN=你的实际域名
   ```

   不要把配置后的 deploy.env 放进作品集或提交到仓库，也不要运行会打印完整环境值的配置检查命令。
4. 将域名解析到服务器，并启动应用及 HTTPS 代理：

   ```sh
   docker compose --env-file deploy.env -f compose.yaml -f compose.public.yaml up -d --build
   ```

   基础配置只向服务器本机绑定 8501；公网只通过代理的 80 / 443。Caddy 配置使用实际域名进行 HTTPS 处理，需要正确的域名解析和网络条件。配置没有开启访问日志，邀请链接也配置了 no-referrer 策略；如自行增加访问日志，应对 invite 查询参数脱敏。
5. 打开 `https://你的实际域名/?admin=1`，用管理员口令登录。

没有域名时，可先将 PUBLIC_URL 设置为 `http://127.0.0.1:8501`，仅运行：

```sh
docker compose --env-file deploy.env up -d --build
```

这一步仅供服务器本机验收，不能直接发给异地参与者。不要为了外网访问而关闭 Streamlit 的 CORS 或 XSRF 保护。

## 你如何收集和导出全部数据

1. 登录 **测试管理后台 → 参与者邀请**。
2. 选择案例、邀请数量和可选的预定义核查标准，点击“创建专属邀请”。
3. 立即下载邀请链接 CSV。每条链接对应一个匿名编号，分别发给参与者。数据库只存令牌哈希，不能再次展示丢失的原链接；必要时撤销旧邀请并创建新邀请。
4. 参与者在浏览器中开始、复核、反馈、确认、查看结果和填写问卷，数据自动保存到服务器。他们可下载自己的记录，但不需要替你执行导出。
5. 你进入 **测试管理后台 → 全量数据与导出 → 导出可用性测试 CSV**，一次获取所有已开始测试的记录，包括完成、进行中和中断状态。

尚未点击开始的邀请不属于“有效测试参与记录”，在邀请表查看，不进入完成率分母。管理员还可在汇总中按预定义标准人工标注错误发现，或删除指定测试数据；删除会同时失效对应邀请。

## 持久化与备份

`compose.yaml` 固定项目名为 `optiflow-study`，使用 `study_data` 数据卷，数据库路径为 `/data/tasks.sqlite3`；trace 与求解文件也在 /data 下。不要使用 `docker compose down -v`，它会删除数据卷；部署时不要随意改项目名或卷名。

建议在停止应用写入后备份整个 /data 目录，或采用 SQLite 在线备份方式；已经导出的 CSV 可额外保留。单份数据卷不是异地备份。容器重启保留提交数据，不代表正在执行的求解作业会自动恢复；异常中断的测试需要组织者跟进，不应统计为完成。

## 当前验证与边界

- 45 项产品回归通过，包含两个独立参与者共用数据库、互相不可读写、邀请恢复与撤销、管理员登录和全量导出，以及实际求解。
- 本机没有 Docker CLI，因此**未实际构建镜像或运行 Compose / Caddy**。Compose 已做结构解析检查，不替代 Docker 验收。
- Windows 临时入口通过本机平台和 Cloudflare 隧道提供 HTTPS；固定服务器、自有域名和 Caddy 证书仍需实际部署验收。临时入口不代表长期服务器已上线，不同地区网络仍需参与者确认。
- 管理员使用一个部署口令，不是企业级账号 / SSO 系统；登录尝试仅有会话内限速。邀请链接相当于访问凭证，应分别发送并妥善保管。
- 当前按小规模、有组织的用户测试设计，未做高并发压测、正式安全审计或多租户合规认证。

部署参考：[Streamlit Docker](https://docs.streamlit.io/deploy/tutorials/docker)、[Docker 持久卷](https://docs.docker.com/engine/storage/volumes/)、[Caddy 反向代理](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy)、[Streamlit 反向代理配置排查](https://docs.streamlit.io/knowledge-base/deploy/remote-start)。
