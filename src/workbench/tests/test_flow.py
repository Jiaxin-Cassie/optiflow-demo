"""Authoritative approval gates, independent UX data and legacy coexistence."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from urllib.parse import parse_qs, urlsplit
from src.workbench.flow import confirm_business, business_confirmed
from src.workbench.hosting import create_invites, ParticipantStore, start_invited_test
from src.workbench.service import prepare_task, confirm_task, solve_task, revise_task
from src.workbench.explanations import decision_summary
from src.workbench.store import TaskStore
from src.workbench.usability import submit_experience, test_records, export_csv


class FlowTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="optiflow_v2_contract_")
        self.addCleanup(folder.cleanup)
        self.store = TaskStore(Path(folder.name) / "tasks.sqlite3")
        self.scoped = self.invite()
        task = start_invited_test(self.scoped)
        self.task = prepare_task(task["task_id"], store=self.scoped)

    def invite(self):
        invitation = create_invites(self.store, "production", 1, "https://example.test", experience_flow="workspace_v2")[0]
        return ParticipantStore(self.store.path, parse_qs(urlsplit(invitation["url"]).query)["invite"][0])

    def test_direct_solver_entry_requires_current_business_and_model_confirmations(self):
        identifier = self.task["task_id"]
        with self.assertRaisesRegex(ValueError, "业务目标"):
            confirm_task(identifier, expected_version=1, store=self.scoped)
        self.assertEqual(self.scoped.get(identifier)["status"], "awaiting_confirmation")
        approved = confirm_business(identifier, expected_version=1, store=self.scoped)
        self.assertTrue(business_confirmed(approved))
        pending = confirm_task(identifier, expected_version=1, store=self.scoped, defer=True)
        pending["business_review"]["model_hash"] = "forged"
        self.scoped.save(pending)
        failed = solve_task(identifier, store=self.scoped)
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["solver"], {})
        self.assertFalse(decision_summary(failed)["eligible"])

    def test_revisions_invalidate_approvals_and_hide_old_recommendations(self):
        identifier = self.task["task_id"]
        confirm_business(identifier, expected_version=1, store=self.scoped)
        solved = confirm_task(identifier, expected_version=1, store=self.scoped)
        self.assertTrue(decision_summary(solved)["eligible"])
        stale = deepcopy(solved)
        stale["business_review"]["version"] = 0
        self.assertFalse(decision_summary(stale)["eligible"])
        revised = revise_task(identifier, "产品 A 最多生产 100 件。", expected_version=1, store=self.scoped)
        self.assertEqual(revised["solver"], {})
        self.assertFalse(business_confirmed(revised))
        self.assertFalse(decision_summary(revised)["eligible"])
        self.assertEqual(revised["versions"][0]["solver"]["objective_value"], 10000)
        with self.assertRaises(ValueError):
            confirm_business(identifier, expected_version=1, store=self.scoped)
        with self.assertRaises(ValueError):
            confirm_task(identifier, expected_version=2, store=self.scoped)
        confirm_business(identifier, expected_version=2, store=self.scoped)
        result = confirm_task(identifier, expected_version=2, store=self.scoped)
        self.assertEqual(result["solver"]["objective_value"], 10000)

    def test_feedback_does_not_change_task_and_is_scoped_and_versioned(self):
        before = self.scoped.get(self.task["task_id"])
        submit_experience(self.scoped, before["usability_test_id"], 4, 5, "没有明显困难", False, improvement="=1+1")
        self.assertEqual(before, self.scoped.get(before["task_id"]))
        row = test_records(self.store)[0]
        self.assertEqual(row["questionnaire_version"], "workspace_ux_v2")
        self.assertEqual(row["protocol"], "workspace_v2")
        self.assertIn("'=1+1", export_csv([row]).decode("utf-8-sig"))
        with self.assertRaises(PermissionError):
            submit_experience(self.invite(), before["usability_test_id"], 4, 5, "确认规则", False)
        with self.assertRaises(ValueError):
            submit_experience(self.scoped, before["usability_test_id"], True, 5, "确认规则", False)
        with self.assertRaises(ValueError):
            submit_experience(self.scoped, before["usability_test_id"], 4, 5, "确认规则", True)

    def test_legacy_invites_and_snapshots_keep_original_protocol(self):
        invitation = create_invites(self.store, "production", 1, "https://example.test")[0]
        scoped = ParticipantStore(self.store.path, parse_qs(urlsplit(invitation["url"]).query)["invite"][0])
        legacy = start_invited_test(scoped)
        original = deepcopy(legacy)
        TaskStore(self.store.path)
        self.assertEqual(original, scoped.get(legacy["task_id"]))
        self.assertEqual(scoped.invite()["experience_flow"], "legacy")
        with self.assertRaises(ValueError):
            submit_experience(scoped, legacy["usability_test_id"], 4, 5, "确认规则", False)

    def test_incomplete_business_information_cannot_be_approved(self):
        from src.workbench.service import model_hash
        task = self.task
        task["model"]["missing_inputs"] = ["资源上限需要业务核实"]
        task["model_hash"] = model_hash(task["model"])
        self.scoped.save(task)
        with self.assertRaisesRegex(ValueError, "缺失"):
            confirm_business(task["task_id"], expected_version=1, store=self.scoped)
        self.assertFalse(business_confirmed(self.scoped.get(task["task_id"])))
