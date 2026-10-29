"""Real task integration, repeat-safe events, study metrics and local data removal."""
import csv
import io
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from src.workbench.service import prepare_task, confirm_task, revise_task, create_task
from src.workbench.cases import CASES
from src.workbench.store import TaskStore
from src.workbench.usability import (start_test, record_view, study_for_task, finish_test, submit_questionnaire,
    test_records, summarize_tests, export_csv, assess_discovery, delete_test)


class UsabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="optiflow_study_")
        self.addCleanup(self.temp.cleanup)
        self.store = TaskStore(Path(self.temp.name) / "tests.sqlite3")

    def start(self, participant="P001", standard=""):
        task = start_test(self.store, participant, "production", uuid4().hex, standard)
        return prepare_task(task["task_id"], store=self.store)

    def test_start_is_persistently_idempotent_and_participants_are_distinct(self):
        token = uuid4().hex
        a = start_test(self.store, "P001", "production", token)
        self.assertEqual(start_test(self.store, "P001", "production", token)["task_id"], a["task_id"])
        self.assertEqual(start_test(TaskStore(self.store.path), "P001", "production", uuid4().hex)["task_id"], a["task_id"])
        b = start_test(self.store, "P002", "production", uuid4().hex)
        self.assertNotEqual(a["task_id"], b["task_id"])
        with self.assertRaises(ValueError):
            start_test(self.store, "P003", "production", token)
        self.assertEqual(len(test_records(self.store)), 2)

    def test_view_events_are_once_per_version_and_do_not_store_original_text(self):
        task = self.start()
        for _ in range(4):
            record_view(self.store, task["task_id"], "model_review_opened")
        task = revise_task(task["task_id"], "A <= 80", expected_version=1, store=self.store)
        for _ in range(2):
            record_view(self.store, task["task_id"], "model_review_opened")
        events = self.store.events(task["task_id"])
        views = [e for e in events if e["name"] == "model_review_opened"]
        self.assertEqual(len(views), 2)
        self.assertEqual([e["payload"]["model_version"] for e in views], [1, 2])
        feedback = [e for e in events if e["name"] == "review_feedback_submitted"]
        self.assertEqual(len(feedback), 1)
        self.assertNotIn("feedback", feedback[0]["payload"])
        self.assertTrue(test_records(self.store)[0]["feedback_submitted"])

    def test_success_completion_questionnaire_export_and_assessment_are_independent(self):
        task = self.start(standard="核对 A 产量上限是否符合本次题目要求")
        study = study_for_task(self.store, task["task_id"])
        record_view(self.store, task["task_id"], "model_review_opened")
        with self.assertRaises(ValueError):
            finish_test(self.store, study["id"])
        task = confirm_task(task["task_id"], expected_version=1, store=self.store)
        self.assertEqual(task["status"], "completed")
        with self.assertRaises(ValueError):
            finish_test(self.store, study["id"])
        record_view(self.store, task["task_id"], "result_viewed")
        finish_test(self.store, study["id"])
        finish_test(self.store, study["id"])
        row = test_records(self.store)[0]
        self.assertEqual(row["status"], "completed")
        self.assertFalse(row["questionnaire_submitted"])
        self.assertTrue(row["model_confirmed"])
        self.assertIsNotNone(row["review_seconds"])
        self.assertIsNone(summarize_tests([row])["discovery_rate"])
        submit_questionnaire(self.store, study["id"], "基本能理解", "判断是否遗漏约束", "")
        assess_discovery(self.store, study["id"], "未发现")
        rows = test_records(self.store)
        self.assertTrue(rows[0]["questionnaire_submitted"])
        self.assertEqual(summarize_tests(rows)["discovery_rate"], 0)
        exported = list(csv.DictReader(io.StringIO(export_csv(rows).decode("utf-8-sig"))))
        self.assertEqual(exported[0]["participant_id"], rows[0]["participant_id"])
        self.assertEqual(exported[0]["status"], "completed")
        self.assertEqual(exported[0]["understanding"], "基本能理解")
        events = self.store.events(task["task_id"])
        self.assertEqual(sum(e["name"] == "usability_test_completed" for e in events), 1)
        self.assertTrue(any(e["name"] == "model_confirmed" for e in events))
        self.assertTrue(any(e["name"] == "review_confirmed" for e in events))
        revise_task(task["task_id"], "A <= 80", expected_version=1, store=self.store)
        self.assertEqual(test_records(self.store)[0]["model_version"], 1)

    def test_interruption_and_unfinished_records_are_never_counted_as_complete(self):
        a = self.start()
        self.start("P002")
        study = study_for_task(self.store, a["task_id"])
        finish_test(self.store, study["id"], interrupted=True)
        rows = test_records(self.store)
        summary = summarize_tests(rows)
        self.assertEqual(summary["started"], 2)
        self.assertEqual(summary["completed"], 0)
        self.assertEqual(summary["completion_rate"], 0)
        self.assertTrue(any(r["status"] == "active" and r["ended_at"] is None for r in rows))
        self.assertTrue(all(r["review_seconds"] is None for r in rows))

    def test_no_standard_means_no_discovery_rating_and_data_can_be_deleted(self):
        ordinary = create_task(CASES["production"]["text"], mode="case", case_id="production", store=self.store)
        task = self.start()
        study = study_for_task(self.store, task["task_id"])
        with self.assertRaises(ValueError):
            assess_discovery(self.store, study["id"], "正确发现")
        with self.assertRaises(ValueError):
            submit_questionnaire(self.store, study["id"], "基本能理解", "其他")
        delete_test(self.store, study["id"])
        self.assertEqual(test_records(self.store), [])
        with self.assertRaises(ValueError):
            self.store.get(task["task_id"])
        self.assertFalse(any(e["payload"].get("test_id") for e in self.store.events(task["task_id"])))
        self.assertEqual(self.store.events(task["task_id"]), [])
        self.assertFalse(list((self.store.path.parent / "traces").glob(f"{task['task_id']}_v*.json")))
        self.assertEqual(self.store.get(ordinary["task_id"])["status"], "pending")

    def test_free_text_csv_is_safe_for_spreadsheets(self):
        row = {"test_id": "one", "participant_id": "P001", "comment": "=1+1"}
        exported = list(csv.DictReader(io.StringIO(export_csv([row]).decode("utf-8-sig"))))
        self.assertEqual(exported[0]["comment"], "'=1+1")
