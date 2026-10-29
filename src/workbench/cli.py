"""All product capabilities are reachable from run_experiment.py."""
import json
import os
from pathlib import Path
import subprocess
import sys

from src.workbench.cases import CASES
from src.workbench.store import TaskStore, DEFAULT_DB, ROOT


def add_arguments(parser):
    parser.add_argument("--share", action="store_true", help="Start a Windows temporary HTTPS entry for invited studies")
    parser.add_argument("--share-status", action="store_true", help="Read the current temporary entry address")
    parser.add_argument("--share-stop", action="store_true", help="Stop this project's temporary entry and owned server processes")
    parser.add_argument("--share-open", action="store_true", help="Check the current entry and open the administrator page")
    parser.add_argument("--workbench", action="store_true", help="Launch the local OptiFlow Streamlit workbench")
    parser.add_argument("--study-server", action="store_true", help="Run invitation-only hosted study and administrator export")
    parser.add_argument("--public-demo", action="store_true", help="Run the isolated public resume demo without invitations")
    parser.add_argument("--demo-db", help="Separate database for the public demo")
    parser.add_argument("--workbench-host", default="127.0.0.1", help="Bind address; public study deployments use 0.0.0.0 behind HTTPS")
    parser.add_argument("--workbench-port", type=int, default=8501)
    parser.add_argument("--workbench-db", default=os.environ.get("OPTIFLOW_DB", str(DEFAULT_DB)))
    parser.add_argument("--workbench-case", choices=list(CASES), help="Build an offline business case, stopping for model confirmation")
    parser.add_argument("--workbench-problem", metavar="UTF8_FILE", help="Build a custom task through the live modeling agents")
    parser.add_argument("--workbench-task", metavar="TASK_ID", help="Read a saved task or apply --workbench-confirm/feedback")
    parser.add_argument("--workbench-confirm", type=int, metavar="VERSION", help="Explicitly confirm this model version and solve")
    parser.add_argument("--workbench-confirm-business", type=int, metavar="VERSION", help="Confirm business understanding for the current model version")
    parser.add_argument("--workbench-feedback", metavar="TEXT")
    parser.add_argument("--workbench-version", type=int, help="Expected model version for feedback")
    parser.add_argument("--workbench-report", metavar="MARKDOWN_FILE")
    parser.add_argument("--workbench-test", action="store_true", help="Run product contract and state-transition tests without API calls")
    parser.add_argument("--workbench-worker", metavar="TASK_ID", help="Internal background worker")
    parser.add_argument("--workbench-action", choices=["prepare", "solve"], default="prepare")


def dispatch(args):
    if args.public_demo and args.study_server:
        raise SystemExit("公开演示和正式用户测试请分别部署。")
    if args.share or args.share_status or args.share_stop or args.share_open:
        from src.workbench.share import serve, read_status, request_stop, open_entry
        if args.share:
            serve()
        elif args.share_open:
            open_entry()
        else:
            print(json.dumps(request_stop() if args.share_stop else read_status(), ensure_ascii=False, indent=2))
        return True
    if args.study_server:
        from src.workbench.hosting import admin_secret
        admin_secret()
        args.workbench = True
    if args.public_demo:
        args.workbench = True
    active = any((args.workbench, args.workbench_case, args.workbench_problem, args.workbench_task,
                  args.workbench_test, args.workbench_worker))
    if not active:
        if args.workbench_confirm is not None or args.workbench_confirm_business is not None or args.workbench_feedback or args.workbench_report:
            raise SystemExit("请使用 --workbench-task 指定任务。")
        return False
    if getattr(args, "dry_run", False):
        raise SystemExit("请使用 --smoke-test 单独执行本地业务案例检查。")
    if args.workbench:
        if args.workbench_host not in {"127.0.0.1", "localhost", "::1"} and not (args.study_server or args.public_demo or os.environ.get("OPTIFLOW_HOSTED_STUDY") == "1"):
            raise SystemExit("对外监听请使用 --study-server，以启用邀请隔离和管理员登录。")
        env = dict(os.environ, OPTIFLOW_DB=str(Path(args.workbench_db).resolve()))
        if args.study_server:
            env["OPTIFLOW_HOSTED_STUDY"] = "1"
        if args.public_demo:
            env["OPTIFLOW_PUBLIC_DEMO"] = "1"
            if args.demo_db:
                env["OPTIFLOW_DEMO_DB"] = str(Path(args.demo_db).resolve())
        browser_options = []
        if env.get("OPTIFLOW_HOSTED_STUDY") == "1" and env.get("OPTIFLOW_PUBLIC_URL"):
            from urllib.parse import urlsplit
            from src.workbench.hosting import public_url
            address = urlsplit(public_url(env["OPTIFLOW_PUBLIC_URL"]))
            browser_options = ["--browser.serverAddress", address.hostname, "--browser.serverPort", str(address.port or (443 if address.scheme == "https" else 80))]
        raise SystemExit(subprocess.call([sys.executable, "-m", "streamlit", "run", str(ROOT / "src/workbench/app.py"),
                                         "--server.address", args.workbench_host, "--server.port", str(args.workbench_port),
                                         "--browser.gatherUsageStats", "false", *browser_options], cwd=ROOT, env=env))
    if args.workbench_test:
        import unittest
        suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern="test_*.py", top_level_dir=str(ROOT))
        if not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful():
            raise SystemExit(1)
        return True
    from src.workbench.service import run_optimization_task, prepare_task, solve_task, confirm_task, revise_task, report_markdown
    store = TaskStore(args.workbench_db)
    if args.workbench_worker:
        try:
            (prepare_task if args.workbench_action == "prepare" else solve_task)(args.workbench_worker, store=store)
        except Exception:
            # Normal stage failures are persisted by the service; never log provider exceptions.
            print("Worker could not claim task. Refresh the saved task state.")
            raise SystemExit(1)
        return True
    if args.workbench_case or args.workbench_problem:
        if args.workbench_confirm is not None or args.workbench_confirm_business is not None or args.workbench_feedback:
            raise SystemExit("请先建模，再使用 --workbench-task 查看并明确确认模型版本。")
        if args.workbench_case:
            case = CASES[args.workbench_case]
            task = run_optimization_task(case["text"], mode="case", case_id=case["id"], title=case["title"], category=case["category"], store=store, workflow_version=2)
        else:
            text = Path(args.workbench_problem).read_text(encoding="utf-8-sig")
            task = run_optimization_task(text, title=Path(args.workbench_problem).stem, store=store, workflow_version=2)
    else:
        if args.workbench_feedback and args.workbench_confirm is not None:
            raise SystemExit("请分别执行反馈重建和模型确认。")
        task = store.get(args.workbench_task)
        if args.workbench_confirm_business is not None:
            from src.workbench.flow import confirm_business
            task = confirm_business(task["task_id"], expected_version=args.workbench_confirm_business, store=store)
        if args.workbench_feedback:
            if args.workbench_version is None:
                raise SystemExit("反馈时请指定 --workbench-version，防止修改过期模型。")
            task = revise_task(task["task_id"], args.workbench_feedback, expected_version=args.workbench_version, store=store)
        if args.workbench_confirm is not None:
            task = confirm_task(task["task_id"], expected_version=args.workbench_confirm, store=store)
    if args.workbench_report:
        Path(args.workbench_report).write_text(report_markdown(task), encoding="utf-8")
    print(json.dumps(task, ensure_ascii=False, indent=2))
    return True

