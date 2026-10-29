"""Shared-server study invitations and task ownership; no participant accounts."""
import hashlib
import hmac
import json
import os
import re
import secrets
from urllib.parse import urlencode, urlsplit
from uuid import uuid4

from src.workbench.store import TaskStore, now


SCHEMA = """
CREATE TABLE IF NOT EXISTS hosted_invites (
 id TEXT PRIMARY KEY, secret_hash TEXT NOT NULL UNIQUE, start_token TEXT NOT NULL UNIQUE,
 participant_id TEXT NOT NULL UNIQUE, case_id TEXT NOT NULL, error_standard TEXT NOT NULL DEFAULT '',
 task_id TEXT UNIQUE, created_at TEXT NOT NULL, revoked_at TEXT
);
"""


def hosted_mode():
    from src.workbench.public_demo import public_demo_mode
    return os.environ.get("OPTIFLOW_HOSTED_STUDY") == "1" or public_demo_mode()


def admin_secret():
    secret = os.environ.get("OPTIFLOW_ADMIN_PASSWORD", "")
    if len(secret) < 16:
        raise ValueError("在线测试模式需要设置至少 16 位的 OPTIFLOW_ADMIN_PASSWORD。")
    return secret


def authenticate_admin(password):
    expected = hashlib.sha256(admin_secret().encode()).digest()
    actual = hashlib.sha256(str(password).encode()).digest()
    return hmac.compare_digest(expected, actual)


def require_manager(store):
    if getattr(store, "participant_hash", None):
        raise PermissionError("此操作仅供测试管理员使用。")


def public_url(value):
    parts = urlsplit(value)
    local = parts.hostname in {"localhost", "127.0.0.1"}
    if (not parts.hostname or parts.username or parts.password or parts.query or parts.fragment or parts.path.strip("/")
            or (parts.scheme != "https" and not (local and parts.scheme == "http"))):
        raise ValueError("请设置 HTTPS 公网地址；本机验收可使用 http://127.0.0.1:端口。")
    return value.rstrip("/")


def issue_invite(conn, case_id, error_standard="", experience_flow="workspace_v2", prefix="P"):
    """Issue a scoped bearer secret; callers must never log this internal result."""
    identifier, secret, participant = uuid4().hex, secrets.token_hex(32), prefix + secrets.token_hex(6).upper()
    conn.execute("INSERT INTO hosted_invites(id,secret_hash,start_token,participant_id,case_id,error_standard,created_at,experience_flow) VALUES (?,?,?,?,?,?,?,?)",
                 (identifier, hashlib.sha256(secret.encode()).hexdigest(), uuid4().hex, participant, case_id, error_standard, now(), experience_flow))
    return identifier, secret, participant


def create_invites(store, case_id, count, base_url, error_standard="", *, experience_flow="legacy"):
    from src.workbench.cases import CASES
    require_manager(store)
    base_url = public_url(base_url)
    if case_id not in CASES or not isinstance(count, int) or isinstance(count, bool) or not 1 <= count <= 50:
        raise ValueError("每批创建 1–50 个有效案例邀请。")
    if not isinstance(error_standard, str) or len(error_standard) > 500:
        raise ValueError("核查标准最多 500 字。")
    if experience_flow not in {"legacy", "workspace_v2"}:
        raise ValueError("未知体验流程。")
    invitations = []
    with store.connection() as conn:
        for _ in range(count):
            identifier, secret, participant = issue_invite(conn, case_id, error_standard, experience_flow)
            invitations.append({"invite_id": identifier, "participant_id": participant, "case_id": case_id,
                                "url": base_url + "/?" + urlencode({"invite": secret})})
    return invitations


def resolve_invite(store, secret):
    if not isinstance(secret, str) or not re.fullmatch(r"[a-f0-9]{64}", secret):
        raise PermissionError("邀请链接无效或已撤销。")
    digest = hashlib.sha256(secret.encode()).hexdigest()
    with store.connection() as conn:
        row = conn.execute("SELECT * FROM hosted_invites WHERE secret_hash=? AND revoked_at IS NULL", (digest,)).fetchone()
    if not row:
        raise PermissionError("邀请链接无效或已撤销。")
    return dict(row)


def list_invites(store):
    require_manager(store)
    with store.connection() as conn:
        rows = conn.execute("SELECT id,participant_id,case_id,task_id,experience_flow,created_at,revoked_at FROM hosted_invites ORDER BY created_at DESC").fetchall()
    return [dict(row) for row in rows]


def revoke_invite(store, identifier):
    require_manager(store)
    with store.connection() as conn:
        conn.execute("UPDATE hosted_invites SET revoked_at=? WHERE id=?", (now(), identifier))


class ParticipantStore(TaskStore):
    """Server-side scope checks, used by both the UI and the existing task services."""
    def __init__(self, path, secret):
        super().__init__(path)
        self.participant_hash = resolve_invite(self, secret)["secret_hash"]

    def invite(self, conn=None):
        if conn is None:
            with self.connection() as connection:
                return self.invite(connection)
        row = conn.execute("SELECT * FROM hosted_invites WHERE secret_hash=? AND revoked_at IS NULL", (self.participant_hash,)).fetchone()
        if not row:
            raise PermissionError("邀请已撤销。")
        return dict(row)

    def assert_access(self, task_id, conn=None):
        if self.invite(conn)["task_id"] != task_id or task_id is None:
            raise PermissionError("无法访问其他参与者的任务。")

    def save(self, task, event=None, payload=None, usability_context=None):
        from src.workbench.usability import register, on_task_event
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            invite = self.invite(conn)
            if task.get("mode") != "case" or task.get("case_id") != invite["case_id"]:
                raise PermissionError("参与者只能运行邀请指定的内置测试案例。")
            if usability_context:
                expected = {"participant_id": invite["participant_id"], "case_id": invite["case_id"],
                            "token": invite["start_token"], "error_standard": invite["error_standard"]}
                if (invite["task_id"] is not None or any(usability_context.get(k) != v for k, v in expected.items())
                        or conn.execute("SELECT 1 FROM tasks WHERE id=?", (task["task_id"],)).fetchone()):
                    raise PermissionError("邀请与测试任务不一致。")
                self._save(conn, task)
                register(conn, task, usability_context)
                conn.execute("UPDATE hosted_invites SET task_id=? WHERE id=?", (task["task_id"], invite["id"]))
            else:
                self.assert_access(task["task_id"], conn)
                self._save(conn, task)
            if event:
                conn.execute("INSERT INTO events(task_id,created_at,name,payload) VALUES (?,?,?,?)",
                             (task["task_id"], now(), event, json.dumps(payload or {}, ensure_ascii=False)))
                on_task_event(conn, task, event)

    def get(self, task_id):
        self.assert_access(task_id)
        return super().get(task_id)

    def claim(self, task_id, allowed, running, expected_version=None, check=None):
        self.assert_access(task_id)
        return super().claim(task_id, allowed, running, expected_version, check=check)

    def events(self, task_id):
        self.assert_access(task_id)
        return super().events(task_id)

    def list(self, limit=200):
        task_id = self.invite()["task_id"]
        return [self.get(task_id)] if task_id else []

    def metrics(self):
        raise PermissionError("参与者不可访问全量管理统计。")


def start_invited_test(store):
    from src.workbench.usability import start_test
    invite = store.invite()
    return start_test(store, invite["participant_id"], invite["case_id"], invite["start_token"], invite["error_standard"],
                      workflow_version=2 if invite["experience_flow"] == "workspace_v2" else 1)
