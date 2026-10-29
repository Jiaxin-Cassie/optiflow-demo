"""SQLite snapshots, durable stage events, model versions and product metrics."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / "runtime" / "tasks.sqlite3"


def now():
    return datetime.now(timezone.utc).isoformat()


class TaskStore:
    def __init__(self, path=DEFAULT_DB):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY, updated_at TEXT NOT NULL, snapshot TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL,
                    created_at TEXT NOT NULL, name TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS event_task ON events(task_id, id);
            """)
            from src.workbench.usability import SCHEMA
            conn.executescript(SCHEMA)
            from src.workbench.hosting import SCHEMA as HOSTED_SCHEMA
            conn.executescript(HOSTED_SCHEMA)
            from src.workbench.manual_study import SCHEMA as MANUAL_SCHEMA
            conn.executescript(MANUAL_SCHEMA)
            step_columns = {row[1] for row in conn.execute("PRAGMA table_info(study_manual_steps)")}
            for column in ("issue_state", "issue", "saved_at"):
                if column not in step_columns:
                    conn.execute(f"ALTER TABLE study_manual_steps ADD COLUMN {column} TEXT")
            if "ended_version" not in {row[1] for row in conn.execute("PRAGMA table_info(usability_tests)")}:
                conn.execute("ALTER TABLE usability_tests ADD COLUMN ended_version INTEGER")
            if "experience_flow" not in {row[1] for row in conn.execute("PRAGMA table_info(hosted_invites)")}:
                conn.execute("ALTER TABLE hosted_invites ADD COLUMN experience_flow TEXT NOT NULL DEFAULT 'legacy'")

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.path, timeout=20)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _save(self, conn, task):
        task["updated_at"] = now()
        conn.execute("INSERT INTO tasks VALUES (?, ?, ?) ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at, snapshot=excluded.snapshot",
                     (task["task_id"], task["updated_at"], json.dumps(task, ensure_ascii=False, allow_nan=False)))

    def save(self, task, event=None, payload=None, usability_context=None):
        with self.connection() as conn:
            self._save(conn, task)
            if usability_context:
                from src.workbench.usability import register
                register(conn, task, usability_context)
            if event:
                conn.execute("INSERT INTO events(task_id, created_at, name, payload) VALUES (?, ?, ?, ?)",
                             (task["task_id"], now(), event, json.dumps(payload or {}, ensure_ascii=False)))
                from src.workbench.usability import on_task_event
                on_task_event(conn, task, event)

    def get(self, task_id):
        with self.connection() as conn:
            if hasattr(self, "assert_access"):
                self.assert_access(task_id, conn)
            row = conn.execute("SELECT snapshot FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not row:
            raise ValueError("任务不存在。")
        return json.loads(row["snapshot"])

    def claim(self, task_id, allowed, running, expected_version=None, check=None):
        """Prevent double confirmation, cross-session edits and simultaneous workers."""
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if hasattr(self, "assert_access"):
                self.assert_access(task_id, conn)
            row = conn.execute("SELECT snapshot FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not row:
                raise ValueError("任务不存在。")
            task = json.loads(row["snapshot"])
            if task["status"] not in allowed:
                raise ValueError("任务状态已变化，请刷新后再操作。")
            if expected_version is not None and task["model_version"] != expected_version:
                raise ValueError("模型版本已变化，请重新查看并确认当前版本。")
            if check:
                check(task)
            task["status"] = running
            self._save(conn, task)
        return task

    def list(self, limit=200):
        with self.connection() as conn:
            rows = conn.execute("SELECT snapshot FROM tasks ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
        return [json.loads(row["snapshot"]) for row in rows]

    def events(self, task_id):
        with self.connection() as conn:
            rows = conn.execute("SELECT * FROM events WHERE task_id=? ORDER BY id", (task_id,)).fetchall()
        return [{**dict(row), "payload": json.loads(row["payload"])} for row in rows]

    def metrics(self):
        with self.connection() as conn:
            rows = conn.execute("SELECT snapshot FROM tasks").fetchall()
            events = conn.execute("SELECT name, COUNT(*) n FROM events GROUP BY name").fetchall()
        tasks = [json.loads(row["snapshot"]) for row in rows]
        counts = {row["name"]: row["n"] for row in events}
        solved = [t for t in tasks if t.get("solver", {}).get("status") == "Optimal"]
        return {"tasks": len(tasks), "models_created": counts.get("model_ready", 0),
                "awaiting_confirmation": sum(t["status"] == "awaiting_confirmation" for t in tasks),
                "open_badcases": sum(bool(t.get("failure")) and t.get("badcase_status") != "已处理" for t in tasks),
                "confirmations": counts.get("model_confirmed", 0), "revisions": counts.get("revision_requested", 0),
                "optimal_tasks": len(solved), "failed_tasks": sum(t["status"] == "failed" for t in tasks),
                "numerically_passed": sum(t.get("validation", {}).get("numerical_feasibility") == "passed" for t in tasks),
                "note": "本地产品使用数据，不代表真实用户规模、商业效果或学术准确率。"}

