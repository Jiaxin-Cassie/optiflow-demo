"""Windows temporary HTTPS entry for the invitation-only study server."""
from datetime import datetime, timezone
import getpass
import hashlib
import html
import json
import os
from pathlib import Path
import platform
import re
import secrets
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from urllib.parse import urlsplit

from src.storage import atomic_json
from src.workbench.store import ROOT, DEFAULT_DB


SHARE_DIR = ROOT / "runtime" / "share"
TOOLS_DIR = ROOT / "runtime" / "tools"
RELEASE_API = "https://api.github.com/repos/cloudflare/cloudflared/releases/latest"


def extract_tunnel_url(log):
    matches = re.findall(r"https://([a-z0-9]+(?:-[a-z0-9]+)+)\.trycloudflare\.com(?![a-z0-9_.-])", log, flags=re.I)
    return f"https://{matches[-1].lower()}.trycloudflare.com" if matches else None


def ensure_tool():
    if platform.machine().lower() not in {"amd64", "x86_64"}:
        raise RuntimeError("当前启动器仅适配 Windows Intel/AMD 64 位系统。")
    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    executable, metadata = TOOLS_DIR / "cloudflared.exe", TOOLS_DIR / "cloudflared.json"
    if executable.exists() and metadata.exists():
        expected = json.loads(metadata.read_text(encoding="utf-8"))["sha256"]
        if hashlib.sha256(executable.read_bytes()).hexdigest() == expected:
            return executable
        raise RuntimeError("隧道程序校验失败，请重新下载官方版本。")
    request = urllib.request.Request(RELEASE_API, headers={"User-Agent": "OptiFlow-Setup"})
    with urllib.request.urlopen(request, timeout=30) as response:
        release = json.load(response)
    asset = next(a for a in release["assets"] if a["name"] == "cloudflared-windows-amd64.exe")
    digest = str(asset.get("digest", ""))
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", digest):
        raise RuntimeError("官方发布缺少可验证的 SHA-256，已停止下载。")
    url = asset["browser_download_url"]
    if urlsplit(url).hostname != "github.com" or not url.startswith("https://github.com/cloudflare/cloudflared/releases/download/"):
        raise RuntimeError("下载地址不是预期的官方发布源。")
    temporary = executable.with_suffix(".download")
    checksum = hashlib.sha256()
    with urllib.request.urlopen(url, timeout=60) as response, temporary.open("wb") as stream:
        while True:
            block = response.read(1024 * 1024)
            if not block:
                break
            stream.write(block)
            checksum.update(block)
    if checksum.hexdigest() != digest.split(":", 1)[1]:
        temporary.unlink(missing_ok=True)
        raise RuntimeError("下载文件与官方校验值不一致，已停止启动。")
    temporary.replace(executable)
    atomic_json(metadata, {"version": release["tag_name"], "sha256": checksum.hexdigest()})
    return executable


def _password(directory):
    path = directory / "后台口令.txt"
    if path.exists():
        password = path.read_text(encoding="utf-8").strip()
        if len(password) < 16:
            raise RuntimeError("本机保存的后台口令长度不足，请重新设置。")
        return password, path
    password = secrets.token_urlsafe(28)
    path.write_text(password, encoding="utf-8")
    if os.name == "nt":
        account = (os.environ.get("USERDOMAIN", "") + "\\" + getpass.getuser()).lstrip("\\")
        result = subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r", account + ":(F)"], capture_output=True,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:
            path.unlink(missing_ok=True)
            raise RuntimeError("无法限制后台口令文件的本机访问权限，已停止启动。")
    else:
        path.chmod(0o600)
    return password, path


def read_status():
    try:
        state = json.loads((SHARE_DIR / "connection.json").read_text(encoding="utf-8"))
        if state.get("state")=="ready":
            stamp=state.get("last_seen") or state.get("started_at")
            elapsed=(datetime.now(timezone.utc)-datetime.fromisoformat(stamp)).total_seconds() if stamp else float("inf")
            if elapsed>30:
                state.update(state="unresponsive",recorded_state="ready",message="服务心跳已过期，旧地址可能失效，请检查或重新启动外网测试。")
        return state
    except (OSError, ValueError, TypeError, AttributeError):
        return {"state": "not_started"}


def _persist_status(path,state):
    """A monitoring file is best effort; failure must never stop healthy children."""
    already_warned=state.pop("status_write_delayed",False)
    try:
        atomic_json(path,state)
        return True
    except OSError:
        state["status_write_delayed"]=True
        if not already_warned:
            print("状态文件暂时无法写入；平台和隧道继续运行，将重试记录。",flush=True)
        return False


def open_entry():
    state=read_status()
    if state.get("state")!="ready":
        raise RuntimeError("外网入口尚未就绪或心跳已过期，请先启动外网测试；不会打开上次的失效地址。")
    try:
        with urllib.request.urlopen(state["public_url"]+"/_stcore/health",timeout=8) as response:
            if response.status!=200 or response.read(32).strip()!=b"ok":
                raise OSError("unhealthy")
    except OSError:
        raise RuntimeError("公网健康检查未通过，请查看隧道日志或稍后重试。") from None
    webbrowser.open(state["admin_url"])


def request_stop():
    SHARE_DIR.mkdir(parents=True, exist_ok=True)
    (SHARE_DIR / "stop_requested").touch()
    for _ in range(50):
        state = read_status()
        if state.get("state") in {"stopped", "error", "not_started"}:
            return state
        if state.get("state")=="unresponsive":
            return {**state,"message":"已发出停止请求；原心跳已过期。如进程已退出，可直接重新启动。"}
        time.sleep(.2)
    return {"state": "stop_requested", "message": "已发出停止请求；若进程被异常强制结束，请检查本机进程。"}


def _free_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def _stop_child(process):
    if process is not None and process.poll() is None:
        if os.name == "nt":
            # Only this controller's live child and its descendants are stopped.
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


def _entry_page(state):
    page = SHARE_DIR / "入口信息.html"
    page.write_text('<!doctype html><meta charset="utf-8"><title>OptiFlow 外网入口</title>'
        '<style>body{font:16px "Microsoft YaHei",sans-serif;max-width:850px;margin:60px auto;line-height:2;color:#18243b}a{color:#315df5}</style>'
        '<h1>OptiFlow 外网测试入口</h1><p>后台：<a href="' + html.escape(state["admin_url"], quote=True) + '">打开测试管理后台</a></p>'
        '<p>后台口令保存在同目录的「后台口令.txt」，不要分享给参与者。</p>'
        '<p>在后台创建专属邀请，再把每人的邀请链接发给对方。公共首页只显示邀请提示。</p>'
        '<p>本次入口：' + html.escape(state["public_url"]) + '</p>'
        '<p>这是临时地址。请保持电脑不休眠、网络和服务持续运行；重新启动入口会改变地址。</p>'
        '<p>数据始终保存在本机 runtime/tasks.sqlite3，停止入口不会删除记录。</p>', encoding="utf-8")


def serve():
    if os.name != "nt":
        raise RuntimeError("此一键临时入口针对 Windows；其他系统请使用在线部署配置。")
    SHARE_DIR.mkdir(parents=True, exist_ok=True)
    import msvcrt
    lock = (SHARE_DIR / "controller.lock").open("a+b")
    lock.seek(0)
    if not lock.read(1):
        lock.write(b"0")
        lock.flush()
    lock.seek(0)
    try:
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        lock.close()
        raise RuntimeError("外网入口已经运行，请查看当前入口信息，或先停止再重启。")
    status_path = SHARE_DIR / "connection.json"
    stop = SHARE_DIR / "stop_requested"
    stop.unlink(missing_ok=True)
    state = {"state": "starting", "manager_pid": os.getpid(), "database": str(DEFAULT_DB),
             "started_at": datetime.now(timezone.utc).isoformat()}
    tunnel = server = None
    flags = subprocess.CREATE_NO_WINDOW
    try:
        _persist_status(status_path, state)
        executable = ensure_tool()
        password, password_path = _password(SHARE_DIR)
        port = _free_port()
        state.update(port=port, admin_password_file=str(password_path), state="connecting")
        _persist_status(status_path, state)
        tunnel_log = SHARE_DIR / "tunnel.log"
        with tunnel_log.open("wb") as output:
            tunnel = subprocess.Popen([str(executable), "tunnel", "--no-autoupdate", "--protocol", "http2",
                                       "--url", f"http://127.0.0.1:{port}"], stdout=output, stderr=output, creationflags=flags)
        url = None
        for _ in range(150):
            if stop.exists():
                return
            if tunnel.poll() is not None:
                raise RuntimeError("隧道进程未能连接，请检查网络或本机 tunnel.log。")
            url = extract_tunnel_url(tunnel_log.read_text(encoding="utf-8", errors="replace"))
            if url:
                break
            time.sleep(1)
        if not url:
            raise RuntimeError("未能获取临时外网地址，请检查网络后重试。")
        env = dict(os.environ, OPTIFLOW_ADMIN_PASSWORD=password, OPTIFLOW_PUBLIC_URL=url, OPTIFLOW_HOSTED_STUDY="1")
        with (SHARE_DIR / "server.log").open("wb") as output:
            server = subprocess.Popen([sys.executable, str(ROOT / "run_experiment.py"), "--study-server", "--workbench-port", str(port),
                                       "--workbench-db", str(DEFAULT_DB)], cwd=ROOT, env=env, stdout=output, stderr=output, creationflags=flags)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        healthy = False
        for _ in range(90):
            if stop.exists():
                return
            if server.poll() is not None:
                raise RuntimeError("本机平台未能启动，请查看 server.log。")
            try:
                with opener.open(f"http://127.0.0.1:{port}/_stcore/health", timeout=2) as response:
                    healthy = response.status == 200
            except OSError:
                pass
            if healthy:
                break
            time.sleep(1)
        if not healthy:
            raise RuntimeError("本机平台启动超时。")
        # Receiving a hostname is not evidence that the public tunnel works.
        reachable = False
        for _ in range(30):
            if stop.exists():
                return
            if tunnel.poll() is not None or server.poll() is not None:
                raise RuntimeError("平台或隧道进程已经退出，请查看本机日志。")
            try:
                with urllib.request.urlopen(url + "/_stcore/health", timeout=5) as response:
                    reachable = response.status == 200 and response.read(32).strip() == b"ok"
            except OSError:
                pass
            if reachable:
                break
            time.sleep(1)
        if not reachable:
            raise RuntimeError("已获取临时域名，但公网健康检查未通过，请检查网络后重试。")
        state.update(state="ready", public_url=url, admin_url=url + "/?admin=1", server_pid=server.pid, tunnel_pid=tunnel.pid)
        try:
            _entry_page(state)
        except OSError:
            print("入口页面暂时无法写入，请使用 --share-status 查看地址。",flush=True)
        _persist_status(status_path, state)
        print(json.dumps({"state": "ready", "admin_url": state["admin_url"], "entry_file": str(SHARE_DIR / "入口信息.html")}, ensure_ascii=False), flush=True)
        while not stop.exists():
            if server.poll() is not None or tunnel.poll() is not None:
                raise RuntimeError("平台或隧道进程已经退出，请重新启动入口。")
            state["last_seen"] = datetime.now(timezone.utc).isoformat()
            _persist_status(status_path, state)
            time.sleep(2)
    except Exception as exc:
        state.update(state="error", error=str(exc) if isinstance(exc, RuntimeError) else "连接失败，请检查本机网络与日志。", error_type=type(exc).__name__)
        _persist_status(status_path, state)
        raise RuntimeError(state["error"]) from None
    finally:
        _stop_child(server)
        _stop_child(tunnel)
        if state.get("state") != "error":
            state["state"] = "stopped"
            _persist_status(status_path, state)
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        lock.close()
