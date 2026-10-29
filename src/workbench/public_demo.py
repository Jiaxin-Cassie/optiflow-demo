"""Public resume deployment: existing UI and solver, isolated visitor scopes."""
import os
from pathlib import Path
import runpy

from src.workbench.cases import CASES
from src.workbench.hosting import ParticipantStore, issue_invite
from src.workbench.store import ROOT, DEFAULT_DB


DEFAULT_DEMO_DB = ROOT / "runtime" / "public_demo" / "tasks.sqlite3"


def public_demo_mode():
    return os.environ.get("OPTIFLOW_PUBLIC_DEMO") == "1"


def demo_database():
    path = Path(os.environ.get("OPTIFLOW_DEMO_DB", str(DEFAULT_DEMO_DB))).resolve()
    private_paths = {DEFAULT_DB.resolve(), Path(os.environ.get("OPTIFLOW_DB", str(DEFAULT_DB))).resolve()}
    if path in private_paths:
        raise ValueError("公开演示数据库必须与正式测试数据库分开。")
    return path


class DemoStore(ParticipantStore):
    """The server retains a per-visitor secret; task ownership checks are unchanged."""
    public_demo = True

    def select_case(self, case_id):
        if case_id not in CASES:
            raise ValueError("请选择内置案例。")
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            invite = self.invite(conn)
            if invite["task_id"]:
                raise ValueError("本次演示已有任务，请开始新的演示后选择案例。")
            conn.execute("UPDATE hosted_invites SET case_id=? WHERE id=?", (case_id, invite["id"]))

    def save(self, task, event=None, payload=None, usability_context=None):
        if task.get("mode") != "case" or task.get("workflow_version") != 2:
            raise PermissionError("公开演示仅运行内置案例与完整确认流程。")
        super().save(task, event, payload, usability_context)

    def claim(self, task_id, allowed, running, expected_version=None, check=None):
        def admitted(task):
            if task.get("mode") != "case" or task.get("workflow_version") != 2:
                raise PermissionError("公开演示仅运行内置案例。")
            if running == "solving":
                # Called inside TaskStore's write transaction, serializing admission.
                with self.connection() as conn:
                    count = conn.execute("SELECT COUNT(*) FROM tasks WHERE id<>? AND json_extract(snapshot,'$.status') IN ('solving','executing')", (task_id,)).fetchone()[0]
                if count >= 3:
                    raise ValueError("当前演示计算较多，请稍后再次点击计算。")
            if check:
                check(task)
        return super().claim(task_id, allowed, running, expected_version, check=admitted)


def visitor_store(manager, secret=None):
    if secret is None:
        with manager.connection() as conn:
            _, secret, _ = issue_invite(conn, "production", prefix="V")
    return DemoStore(manager.path, secret), secret


def cloud_entry():
    """Streamlit Cloud calls this on every script rerun, never through import caching."""
    os.environ["OPTIFLOW_PUBLIC_DEMO"] = "1"
    runpy.run_path(str(ROOT / "src/workbench/app.py"), run_name="__main__")
