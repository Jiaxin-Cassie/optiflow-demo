"""Public resume deployment keeps the proven flow and scopes visitors on the server."""
import argparse
import ast
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from streamlit.testing.v1 import AppTest

from src.workbench.cases import CASES
from src.workbench.cli import add_arguments, dispatch
from src.workbench.flow import confirm_business
from src.workbench.hosting import start_invited_test
from src.workbench.package import build_package
from src.workbench.public_demo import visitor_store, demo_database
from src.workbench.service import prepare_task, confirm_task, solve_task, create_task
from src.workbench.store import ROOT, DEFAULT_DB, TaskStore


class PublicDemoTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="optiflow_resume_")
        self.addCleanup(folder.cleanup)
        self.store = TaskStore(Path(folder.name) / "demo.sqlite3")

    def test_visitor_scopes_and_paid_model_access_are_enforced(self):
        a, secret = visitor_store(self.store)
        b, _ = visitor_store(self.store)
        task = start_invited_test(a)
        self.assertEqual(task["experience_channel"], "public_demo")
        self.assertEqual(visitor_store(self.store, secret)[0].get(task["task_id"]), task)
        with self.assertRaises(PermissionError):
            b.get(task["task_id"])
        with self.assertRaises(PermissionError):
            b.save(task)
        with self.assertRaises(PermissionError):
            create_task(CASES["production"]["text"], mode="live", workflow_version=2, store=b)
        self.assertEqual(len(self.store.list()), 1)

    def test_demo_database_cannot_be_the_formal_study_database(self):
        with patch.dict(os.environ, {"OPTIFLOW_DEMO_DB": str(DEFAULT_DB)}):
            with self.assertRaises(ValueError):
                demo_database()
        custom = str(self.store.path)
        with patch.dict(os.environ, {"OPTIFLOW_DB": custom, "OPTIFLOW_DEMO_DB": custom}):
            with self.assertRaises(ValueError):
                demo_database()

    def test_case_selection_and_concurrent_solver_admission(self):
        ready = []
        for _ in range(4):
            scoped, _ = visitor_store(self.store)
            scoped.select_case("allocation")
            task = start_invited_test(scoped)
            task = prepare_task(task["task_id"], store=scoped)
            confirm_business(task["task_id"], expected_version=1, store=scoped)
            ready.append((scoped, task["task_id"]))
        for scoped, identifier in ready[:3]:
            confirm_task(identifier, expected_version=1, store=scoped, defer=True)
        scoped, identifier = ready[3]
        with self.assertRaisesRegex(ValueError, "计算较多"):
            confirm_task(identifier, expected_version=1, store=scoped, defer=True)
        self.assertEqual(scoped.get(identifier)["status"], "awaiting_confirmation")
        first, identifier = ready[0]
        self.assertEqual(solve_task(identifier, store=first)["solver"]["objective_value"], 195)
        scoped, identifier = ready[3]
        self.assertEqual(confirm_task(identifier, expected_version=1, store=scoped, defer=True)["status"], "solving")

    def test_cli_public_mode_requires_no_admin_password_and_keeps_separate_db(self):
        parser = argparse.ArgumentParser()
        add_arguments(parser)
        args = parser.parse_args(["--public-demo", "--workbench-host", "0.0.0.0", "--demo-db", str(self.store.path)])
        with patch.dict(os.environ, {"OPTIFLOW_ADMIN_PASSWORD": "", "OPTIFLOW_HOSTED_STUDY": "0"}), patch("src.workbench.cli.subprocess.call", return_value=0) as launch:
            with self.assertRaises(SystemExit) as result:
                dispatch(args)
            self.assertEqual(result.exception.code, 0)
            self.assertEqual(launch.call_args.kwargs["env"]["OPTIFLOW_PUBLIC_DEMO"], "1")
            self.assertEqual(launch.call_args.kwargs["env"]["OPTIFLOW_DEMO_DB"], str(self.store.path.resolve()))

    def test_two_public_browser_sessions_use_existing_ui_and_real_solver(self):
        env = {"OPTIFLOW_DEMO_DB": str(self.store.path), "OPTIFLOW_PUBLIC_DEMO": "1", "OPTIFLOW_HOSTED_STUDY": "0", "OPTIFLOW_ADMIN_PASSWORD": ""}
        def worker(identifier, action, store):
            return (prepare_task if action == "prepare" else solve_task)(identifier, store=store)
        with patch.dict(os.environ, env), patch("src.workbench.jobs.launch", side_effect=worker):
            a = AppTest.from_file(str(ROOT / "resume_demo.py"), default_timeout=60).run()
            b = AppTest.from_file(str(ROOT / "resume_demo.py"), default_timeout=60).run()
            def click(app, label):
                next(x for x in app.button if x.label == label).click().run()
                self.assertFalse(list(app.exception))
            self.assertNotEqual(a.session_state["demo_visitor_secret"], b.session_state["demo_visitor_secret"])
            click(a, "开始体验")
            self.assertFalse(any(r.label == "需求来源" for r in a.radio))
            self.assertFalse(any(x.label == "测试管理后台" for x in a.button))
            click(a, "让系统分析需求")
            identifier = a.session_state["task_id"]
            click(a, "4 查看方案")
            self.assertTrue(any("前面的确认" in x.value for x in a.title))
            click(a, "返回当前步骤")
            click(a, "确认无误，继续")
            click(a, "确认模型并计算方案")
            self.assertTrue(any("10,000.00" in x.value for x in a.metric))
            click(b, "开始体验")
            next(x for x in b.selectbox if x.label == "选择业务案例").set_value("allocation").run()
            click(b, "让系统分析需求")
            self.assertNotEqual(identifier, b.session_state["task_id"])
            self.assertEqual(self.store.get(b.session_state["task_id"])["case_id"], "allocation")
            click(a, "重新开始演示")
            self.assertFalse(any("继续我的方案" == x.label for x in a.button))
            admin = AppTest.from_file(str(ROOT / "resume_demo.py"), default_timeout=60)
            admin.query_params["admin"] = "1"
            admin.run()
            self.assertFalse(list(admin.exception))
            self.assertFalse(any("导出" in x.label for x in admin.button))
            self.assertTrue(any("未启用管理后台" in x.value for x in admin.info))

    def test_resume_archive_has_cloud_entry_and_excludes_credentials_and_records(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "runtime", prefix="resume_package_") as folder:
            destination = Path(folder) / "resume.zip"
            build_package(destination, profile="resume")
            with ZipFile(destination) as archive:
                names = archive.namelist()
                self.assertIn("resume_demo.py", names)
                self.assertIn("src/workbench/public_demo.py", names)
                self.assertFalse(any(n.startswith("runtime/") or n.endswith((".sqlite3", ".env", "secrets.toml")) for n in names))
                self.assertIn(b'streamlit==1.65.0', archive.read("requirements.txt"))
                self.assertIn(b'address = "0.0.0.0"', archive.read(".streamlit/config.toml"))
                tree = ast.parse(archive.read("src/config.py").decode("utf-8"))
                keys = [n.value.value for n in tree.body if isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant)
                        and any(isinstance(t, ast.Name) and t.id == "HARDCODED_API_KEY" for t in n.targets)]
                self.assertEqual(keys, [""])
