"""Separate browser sessions for online administrator and participant entry points."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit, parse_qs

from streamlit.testing.v1 import AppTest
from src.workbench.hosting import create_invites, ParticipantStore, start_invited_test
from src.workbench.service import prepare_task, solve_task
from src.workbench.store import ROOT, TaskStore


class HostedUITests(unittest.TestCase):
    def test_visitor_and_admin_login_are_gated(self):
        with tempfile.TemporaryDirectory(prefix="optiflow_admin_ui_") as folder:
            db = str(Path(folder) / "shared.sqlite3")
            env = {"OPTIFLOW_DB": db, "OPTIFLOW_HOSTED_STUDY": "1", "OPTIFLOW_ADMIN_PASSWORD": "test-only-manager-password"}
            with patch.dict(os.environ, env):
                visitor = AppTest.from_file(str(ROOT / "src/workbench/app.py")).run()
                self.assertFalse(list(visitor.exception))
                self.assertEqual(len(visitor.sidebar.radio), 0)
                admin = AppTest.from_file(str(ROOT / "src/workbench/app.py"), default_timeout=60)
                admin.query_params["admin"] = "1"
                admin.run()
                self.assertFalse(list(admin.exception))
                self.assertEqual(len(admin.sidebar.radio), 0)
                admin.text_input[0].set_value("wrong")
                next(b for b in admin.button if b.label == "进入管理后台").click().run()
                self.assertTrue(list(admin.error))
                admin.text_input[0].set_value("test-only-manager-password")
                next(b for b in admin.button if b.label == "进入管理后台").click().run()
                self.assertFalse(list(admin.exception))
                self.assertEqual(admin.session_state["of_view"], "admin")
                self.assertTrue(any(t.label == "全量数据与导出" for t in admin.tabs))
                next(b for b in admin.button if b.label == "退出管理员登录").click().run()
                self.assertEqual(len(admin.sidebar.radio), 0)

    def test_participant_only_sees_invited_task_and_can_use_original_flow(self):
        with tempfile.TemporaryDirectory(prefix="optiflow_invited_ui_") as folder:
            db = str(Path(folder) / "shared.sqlite3")
            store = TaskStore(db)
            invitation = create_invites(store, "production", 1, "https://study.example.test")[0]
            secret = parse_qs(urlsplit(invitation["url"]).query)["invite"][0]
            # An invitation started before the manual upgrade keeps its original protocol.
            start_invited_test(ParticipantStore(store.path, secret))
            def worker(task_id, action, store):
                return (prepare_task if action == "prepare" else solve_task)(task_id, store=store)
            env = {"OPTIFLOW_DB": db, "OPTIFLOW_HOSTED_STUDY": "1", "OPTIFLOW_ADMIN_PASSWORD": "test-only-manager-password"}
            with patch.dict(os.environ, env), patch("src.workbench.jobs.launch", side_effect=worker):
                app = AppTest.from_file(str(ROOT / "src/workbench/app.py"), default_timeout=60)
                app.query_params["invite"] = secret
                app.run()
                self.assertFalse(list(app.exception))
                self.assertNotIn("任务记录与 Badcase", app.sidebar.radio[0].options)
                self.assertNotIn("测试管理后台", app.sidebar.radio[0].options)
                next(b for b in app.button if b.label == "开始 / 继续我的测试").click().run()
                self.assertFalse(list(app.exception))
                next(b for b in app.button if b.label == "检查并确认模型").click().run()
                app.checkbox[0].check().run()
                next(b for b in app.button if b.label == "确认模型并求解").click().run()
                next(b for b in app.button if b.label == "查看求解结果").click().run()
                self.assertFalse(list(app.exception))
                self.assertTrue(any(m.value == "10,000.00" for m in app.metric))
