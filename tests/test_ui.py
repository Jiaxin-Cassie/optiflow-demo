"""Acceptance journeys for the four-stage workspace using isolated fixtures."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from streamlit.testing.v1 import AppTest
from src.workbench.service import prepare_task, solve_task
from src.workbench.store import TaskStore, ROOT
from src.workbench.usability import test_records, export_csv


class UITests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="optiflow_v2_ui_")
        self.addCleanup(folder.cleanup)
        self.store = TaskStore(Path(folder.name) / "tasks.sqlite3")
        env = patch.dict(os.environ, {"OPTIFLOW_DB": str(self.store.path), "OPTIFLOW_HOSTED_STUDY": "0"})
        env.start()
        self.addCleanup(env.stop)
        worker = patch("src.workbench.jobs.launch", side_effect=lambda task_id, action, store:
                       (prepare_task if action == "prepare" else solve_task)(task_id, store=store))
        worker.start()
        self.addCleanup(worker.stop)
        self.app = AppTest.from_file(str(ROOT / "src/workbench/app.py"), default_timeout=60).run()

    def click(self, label):
        next(b for b in self.app.button if b.label == label).click().run()
        self.assertFalse(list(self.app.exception), label)

    def begin(self):
        self.click("开始体验")
        self.click("让系统分析需求")
        return self.store.get(self.app.session_state["task_id"])

    def approve(self):
        self.click("确认无误，继续")
        self.click("确认模型并计算方案")

    def revise(self, text):
        self.click("需要修改")
        next(t for t in self.app.text_area if t.label == "补充或修改需求").set_value(text)
        self.click("提交修改并重新建模")

    def test_first_use_and_both_confirmations_need_no_written_feedback(self):
        self.assertTrue(any("用一句话" in x.value for x in self.app.title))
        self.assertEqual(len(self.store.list()), 0)
        task = self.begin()
        self.assertEqual(task["workflow_version"], 2)
        self.assertFalse(self.app.text_area)
        self.click("确认无误，继续")
        self.assertTrue(any(e.label == "展开变量、目标函数、约束与 JSON" and not e.proto.expanded for e in self.app.expander))
        self.app.run().run()
        self.assertEqual(sum(e["name"] == "model_review_opened" for e in self.store.events(task["task_id"])), 1)
        self.click("确认模型并计算方案")
        self.assertTrue(any("建议安排" in x.value for x in self.app.markdown))
        self.assertTrue(any("10,000.00" in x.value for x in self.app.metric))
        self.assertTrue(any("未独立验证" in x.value for x in self.app.caption))
        self.assertFalse(test_records(self.store)[0]["questionnaire_submitted"])

    def test_step_navigation_cannot_skip_business_or_model_approval(self):
        task = self.begin()
        self.click("4 查看方案")
        self.assertTrue(any("确认规则" in x.value for x in self.app.markdown))
        self.assertFalse(any(b.label == "确认模型并计算方案" for b in self.app.button))
        self.click("返回当前步骤")
        self.click("确认无误，继续")
        self.click("4 查看方案")
        self.assertTrue(any("确认模型并计算方案" in x.value for x in self.app.markdown))
        self.assertEqual(self.store.get(task["task_id"])["solver"], {})
        self.click("返回当前步骤")
        self.click("确认模型并计算方案")

    def test_revision_before_first_solve_and_later_revision_clear_stale_results(self):
        task = self.begin()
        self.revise("产品 A 最多生产 100 件。")
        updated = self.store.get(task["task_id"])
        self.assertEqual(updated["model_version"], 2)
        self.assertEqual(updated["business_review"]["status"], "pending")
        self.assertEqual(updated["solver"], {})
        self.approve()
        self.assertTrue(any("10,000.00" in x.value for x in self.app.metric))
        self.revise("产品 A 最多生产 80 件。")
        self.assertFalse(any("建议安排" in x.value for x in self.app.markdown))
        self.assertEqual(self.store.get(task["task_id"])["solver"], {})
        self.approve()
        self.assertTrue(any("9,500.00" in x.value for x in self.app.metric))
        self.assertTrue(any(e.label == "查看历史版本、前后对比与导出" for e in self.app.expander))

    def test_feedback_is_optional_independent_and_visible_in_admin_export(self):
        task = self.begin()
        self.click("体验反馈")
        next(r for r in self.app.radio if r.label.startswith("1.")).set_value(4)
        next(r for r in self.app.radio if r.label.startswith("2.")).set_value(3)
        next(s for s in self.app.selectbox if s.label.startswith("3.")).set_value("确认规则")
        next(r for r in self.app.radio if r.label.startswith("4.")).set_value("有")
        next(t for t in self.app.text_area if t.label.startswith("问题说明")).set_value("验收记录：想知道确认和求解的区别。")
        self.click("提交体验反馈")
        self.assertEqual(self.store.get(task["task_id"])["model_version"], 1)
        self.assertEqual(self.store.get(task["task_id"])["human_review"]["status"], "pending")
        row = test_records(self.store)[0]
        self.assertEqual(row["status"], "active")
        self.assertEqual(row["ease"], 4)
        self.assertIn("验收记录", export_csv([row]).decode("utf-8-sig"))
        self.click("返回工作台")
        self.approve()
        self.click("完成体验，填写反馈")
        self.assertEqual(test_records(self.store)[0]["status"], "completed")
        self.click("测试管理后台")
        self.assertTrue(any(e.label == "查看新版体验反馈" for e in self.app.expander))

    def test_infeasible_result_has_no_recommendation_and_advanced_tools_remain_available(self):
        self.begin()
        self.revise("产品 A 至少生产 1000 件。")
        self.approve()
        self.assertTrue(list(self.app.error))
        self.assertFalse(any("建议安排：" in x.value for x in self.app.markdown))
        for page in ["任务记录与 Badcase", "建模技能库", "服务与能力"]:
            self.click(page)
