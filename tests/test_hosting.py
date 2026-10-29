"""Shared-server persistence, participant scoping and administrator exports."""
from pathlib import Path
import argparse
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4
from urllib.parse import parse_qs, urlsplit

from src.workbench.hosting import (create_invites, resolve_invite, list_invites, revoke_invite,
    ParticipantStore, start_invited_test, authenticate_admin)
from src.workbench.service import prepare_task, confirm_task, create_task
from src.workbench.cases import CASES
from src.workbench.store import TaskStore
from src.workbench.usability import (test_records, record_view, study_for_task, finish_test,
    submit_questionnaire, export_csv, assess_discovery, delete_test, start_test)


def token(invite):
    return parse_qs(urlsplit(invite["url"]).query)["invite"][0]


class HostingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="optiflow_hosted_")
        self.addCleanup(self.temp.cleanup)
        self.store = TaskStore(Path(self.temp.name) / "shared.sqlite3")
        self.links = create_invites(self.store, "production", 2, "https://study.example.test")
        self.a = ParticipantStore(self.store.path, token(self.links[0]))
        self.b = ParticipantStore(self.store.path, token(self.links[1]))

    def test_invites_store_only_hashes_and_admin_password_is_checked(self):
        with self.store.connection() as conn:
            rows = conn.execute("SELECT * FROM hosted_invites").fetchall()
        self.assertNotIn(token(self.links[0]), str([dict(r) for r in rows]))
        with patch.dict("os.environ", {"OPTIFLOW_ADMIN_PASSWORD": "test-only-admin-password"}):
            self.assertTrue(authenticate_admin("test-only-admin-password"))
            self.assertFalse(authenticate_admin("wrong"))
        with self.assertRaises(ValueError):
            create_invites(self.store, "production", 1, "http://unsecured.example.test")

    def test_hosted_command_passes_shared_storage_and_browser_domain(self):
        from src.workbench.cli import add_arguments, dispatch
        parser = argparse.ArgumentParser()
        add_arguments(parser)
        args = parser.parse_args(["--study-server", "--workbench-host", "0.0.0.0", "--workbench-db", str(self.store.path)])
        with patch.dict("os.environ", {"OPTIFLOW_ADMIN_PASSWORD": "test-only-manager-password", "OPTIFLOW_PUBLIC_URL": "https://study.example.test"}), \
             patch("src.workbench.cli.subprocess.call", return_value=0) as launch:
            with self.assertRaises(SystemExit) as result:
                dispatch(args)
            self.assertEqual(result.exception.code, 0)
            call = launch.call_args
            self.assertIn("study.example.test", call.args[0])
            self.assertIn("443", call.args[0])
            self.assertNotIn("test-only-manager-password", str(call.args[0]))
            self.assertEqual(call.kwargs["env"]["OPTIFLOW_HOSTED_STUDY"], "1")
            self.assertEqual(call.kwargs["env"]["OPTIFLOW_DB"], str(self.store.path.resolve()))

    def test_public_binding_requires_study_mode(self):
        from src.workbench.cli import add_arguments, dispatch
        parser = argparse.ArgumentParser()
        add_arguments(parser)
        args = parser.parse_args(["--workbench", "--workbench-host", "0.0.0.0"])
        with patch.dict("os.environ", {"OPTIFLOW_HOSTED_STUDY": "0"}):
            with self.assertRaises(SystemExit):
                dispatch(args)

    def test_two_remote_participants_share_database_but_cannot_read_or_change_peers(self):
        ordinary = create_task(CASES["production"]["text"], mode="case", case_id="production", store=self.store)
        invitation = self.a.invite()
        context = {"id": uuid4().hex, "token": invitation["start_token"], "participant_id": invitation["participant_id"],
                   "case_id": invitation["case_id"], "error_standard": invitation["error_standard"]}
        with self.assertRaises(PermissionError):
            self.a.save(ordinary, event="task_created", usability_context=context)
        self.assertEqual(self.store.get(ordinary["task_id"])["status"], "pending")
        a = start_invited_test(self.a)
        b = start_invited_test(self.b)
        self.assertNotEqual(a["task_id"], b["task_id"])
        self.assertEqual(len(test_records(self.store)), 2)
        self.assertEqual(len(test_records(self.a)), 1)
        self.assertEqual(self.a.list()[0]["task_id"], a["task_id"])
        for access in (lambda: self.a.get(b["task_id"]), lambda: self.a.events(b["task_id"]),
                       lambda: self.a.claim(b["task_id"], {"pending"}, "modeling"),
                       lambda: self.a.save(b), lambda: record_view(self.a, b["task_id"], "model_review_opened"),
                       lambda: self.a.metrics()):
            with self.assertRaises(PermissionError):
                access()
        self.assertEqual(self.store.get(b["task_id"])["status"], "pending")

    def test_reconnect_resumes_own_task_and_revocation_blocks_future_reads(self):
        task = start_invited_test(self.a)
        reopened = ParticipantStore(self.store.path, token(self.links[0]))
        self.assertEqual(start_invited_test(reopened)["task_id"], task["task_id"])
        revoke_invite(self.store, self.links[0]["invite_id"])
        with self.assertRaises(PermissionError):
            reopened.get(task["task_id"])
        with self.assertRaises(PermissionError):
            resolve_invite(self.store, token(self.links[0]))

    def test_participant_cannot_create_other_studies_or_administer_records(self):
        a = start_invited_test(self.a)
        b = start_invited_test(self.b)
        study = study_for_task(self.store, b["task_id"])
        for access in (lambda: create_invites(self.a, "production", 1, "https://study.example.test"),
                       lambda: list_invites(self.a), lambda: revoke_invite(self.a, self.links[1]["invite_id"]),
                       lambda: assess_discovery(self.a, study["id"], "正确发现"),
                       lambda: delete_test(self.a, study["id"]), lambda: finish_test(self.a, study["id"], interrupted=True),
                       lambda: submit_questionnaire(self.a, study["id"], "基本能理解", "其他"),
                       lambda: start_test(self.a, self.links[1]["participant_id"], "production", uuid4().hex)):
            with self.assertRaises(PermissionError):
                access()

    def test_invited_task_uses_real_solver_and_all_data_is_available_to_manager(self):
        task = start_invited_test(self.a)
        task = prepare_task(task["task_id"], store=self.a)
        self.assertEqual(task["status"], "awaiting_confirmation")
        record_view(self.a, task["task_id"], "model_review_opened")
        task = confirm_task(task["task_id"], expected_version=1, store=self.a)
        self.assertEqual(task["status"], "completed", task.get("failure"))
        self.assertEqual(task["solver"]["objective_value"], 10000)
        record_view(self.a, task["task_id"], "result_viewed")
        study = study_for_task(self.a, task["task_id"])
        finish_test(self.a, study["id"])
        submit_questionnaire(self.a, study["id"], "基本能理解", "其他")
        start_invited_test(self.b)
        rows = test_records(TaskStore(self.store.path))
        self.assertEqual(len(rows), 2)
        csv = export_csv(rows).decode("utf-8-sig")
        self.assertIn(self.links[0]["participant_id"], csv)
        self.assertIn(self.links[1]["participant_id"], csv)
        own = export_csv(test_records(self.a)).decode("utf-8-sig")
        self.assertNotIn(self.links[1]["participant_id"], own)
