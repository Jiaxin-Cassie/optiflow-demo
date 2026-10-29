"""Anonymous local usability sessions layered on the existing task/event store."""
import csv
from datetime import datetime, timezone
import io
import json
import re
import shutil
import sqlite3
from uuid import uuid4


UNDERSTANDING = ["完全能理解", "基本能理解", "不太能理解", "完全无法理解"]
DIFFICULTIES = ["理解业务规则", "判断是否遗漏约束", "补充修改需求", "理解决策结果", "其他"]
ASSESSMENTS = ["未评定", "正确发现", "未发现", "误报"]
SCHEMA = """
CREATE TABLE IF NOT EXISTS usability_tests (
 id TEXT PRIMARY KEY, task_id TEXT NOT NULL UNIQUE, start_token TEXT NOT NULL UNIQUE,
 participant_id TEXT NOT NULL, case_id TEXT NOT NULL, started_at TEXT NOT NULL,
 ended_at TEXT, ended_version INTEGER, status TEXT NOT NULL DEFAULT 'active', error_standard TEXT NOT NULL DEFAULT '',
 assessment TEXT NOT NULL DEFAULT '未评定', questionnaire TEXT,
 FOREIGN KEY(task_id) REFERENCES tasks(id)
);
CREATE UNIQUE INDEX IF NOT EXISTS usability_active ON usability_tests(participant_id, case_id) WHERE status='active';
CREATE TABLE IF NOT EXISTS usability_event_keys (key TEXT PRIMARY KEY, task_id TEXT NOT NULL);
"""


def _now():
    return datetime.now(timezone.utc).isoformat()


def _emit(conn, study, name, version, extra=None):
    # Deduplication lives in SQLite, not Session State, so refresh/reconnect is safe.
    key = f"{study['id']}:{name}:v{version}"
    cursor = conn.execute("INSERT OR IGNORE INTO usability_event_keys VALUES (?,?)", (key, study["task_id"]))
    if cursor.rowcount:
        payload = {"test_id": study["id"], "participant_id": study["participant_id"], "case_id": study["case_id"],
                   "model_version": version, **(extra or {})}
        conn.execute("INSERT INTO events(task_id,created_at,name,payload) VALUES (?,?,?,?)",
                     (study["task_id"], _now(), name, json.dumps(payload, ensure_ascii=False)))


def register(conn, task, context):
    manual = conn.execute("SELECT started_at FROM study_manual_sessions WHERE start_token=?", (context["token"],)).fetchone()
    conn.execute("INSERT INTO usability_tests(id,task_id,start_token,participant_id,case_id,started_at,error_standard) VALUES (?,?,?,?,?,?,?)",
                 (context["id"], task["task_id"], context["token"], context["participant_id"], context["case_id"], manual["started_at"] if manual else _now(), context["error_standard"]))
    conn.execute("UPDATE study_manual_sessions SET task_id=? WHERE start_token=?", (task["task_id"], context["token"]))
    study = dict(conn.execute("SELECT * FROM usability_tests WHERE id=?", (context["id"],)).fetchone())
    _emit(conn, study, "usability_test_started", 0)


def on_task_event(conn, task, event):
    names = {"model_confirmed": "review_confirmed", "revision_requested": "review_feedback_submitted"}
    if event not in names:
        return
    row = conn.execute("SELECT * FROM usability_tests WHERE task_id=? AND status='active'", (task["task_id"],)).fetchone()
    if row:
        _emit(conn, dict(row), names[event], task["model_version"])


def start_test(store, participant_id, case_id, token, error_standard="", *, workflow_version=1):
    from src.workbench.cases import CASES
    from src.workbench.service import create_task
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{1,31}", participant_id or ""):
        raise ValueError("请使用匿名编号，如 P001；不要填写真实姓名或联系方式。")
    if case_id not in CASES or not re.fullmatch(r"[a-f0-9]{32}", token or ""):
        raise ValueError("测试案例或启动标识无效。")
    if not isinstance(error_standard, str) or len(error_standard) > 500:
        raise ValueError("测试设计标准最多 500 字。")
    def existing():
        with store.connection() as conn:
            row = conn.execute("SELECT task_id,participant_id,case_id FROM usability_tests WHERE start_token=? OR (participant_id=? AND case_id=? AND status='active') ORDER BY started_at LIMIT 1",
                               (token, participant_id, case_id)).fetchone()
        if row and (row["participant_id"] != participant_id or row["case_id"] != case_id):
            raise ValueError("启动标识已用于另一位参与者或案例，请开始另一次测试。")
        return store.get(row["task_id"]) if row else None
    previous = existing()
    if previous:
        return previous
    case = CASES[case_id]
    context = {"id": uuid4().hex, "token": token, "participant_id": participant_id, "case_id": case_id, "error_standard": error_standard}
    try:
        return create_task(case["text"], mode="case", case_id=case_id, title=f"可用性测试 · {case['title']}",
                           category=case["category"], store=store, usability_context=context, workflow_version=workflow_version)
    except sqlite3.IntegrityError:
        previous = existing()
        if previous:
            return previous
        raise


def study_for_task(store, task_id):
    store.get(task_id)
    with store.connection() as conn:
        row = conn.execute("SELECT * FROM usability_tests WHERE task_id=?", (task_id,)).fetchone()
    return dict(row) if row else None


def record_view(store, task_id, name):
    store.get(task_id)
    if name not in {"model_review_opened", "result_viewed", "comparison_viewed"}:
        raise ValueError("未知页面事件。")
    with store.connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        study = conn.execute("SELECT * FROM usability_tests WHERE task_id=? AND status='active'", (task_id,)).fetchone()
        row = conn.execute("SELECT snapshot FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not study or not row:
            return
        task = json.loads(row["snapshot"])
        if name == "model_review_opened" and not task.get("model"):
            return
        if name == "result_viewed" and not task.get("solver"):
            return
        if name == "comparison_viewed":
            from src.workbench.manual_study import baseline
            from src.workbench.explanations import compare_versions
            old = baseline(task)
            if not old or task["model_version"] <= 1 or not compare_versions(old, task)["comparable"]:
                return
        _emit(conn, dict(study), name, task["model_version"])


def finish_test(store, test_id, *, interrupted=False):
    from src.workbench.explanations import decision_summary
    with store.connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        study = conn.execute("SELECT * FROM usability_tests WHERE id=?", (test_id,)).fetchone()
        if not study:
            raise ValueError("测试不存在。")
        store.get(study["task_id"])
        if study["status"] != "active":
            return
        task = json.loads(conn.execute("SELECT snapshot FROM tasks WHERE id=?", (study["task_id"],)).fetchone()["snapshot"])
        viewed = conn.execute("SELECT 1 FROM usability_event_keys WHERE key=?", (f"{test_id}:result_viewed:v{task['model_version']}",)).fetchone()
        if not interrupted and (not decision_summary(task)["eligible"] or not viewed):
            raise ValueError("请完成当前版本的模型确认、求解并查看结果后，再标记测试完成。")
        manual = conn.execute("SELECT start_token FROM study_manual_sessions WHERE task_id=?", (study["task_id"],)).fetchone()
        if not interrupted and manual:
            count = conn.execute("SELECT COUNT(*) FROM study_manual_steps WHERE start_token=? AND submitted_at IS NOT NULL", (manual["start_token"],)).fetchone()[0]
            if count != 6:
                raise ValueError("请按测试手册完成并记录 T1–T6，再进入结束问卷；无法继续时可结束为未完成。")
        status = "interrupted" if interrupted else "completed"
        conn.execute("UPDATE usability_tests SET status=?,ended_at=?,ended_version=? WHERE id=?", (status, _now(), task["model_version"], test_id))
        _emit(conn, dict(study), "usability_test_interrupted" if interrupted else "usability_test_completed", task["model_version"])


def submit_questionnaire(store, test_id, understanding, difficulty, comment="", *, interview=None, difficulty_other=""):
    if understanding not in UNDERSTANDING or difficulty not in DIFFICULTIES or not isinstance(comment, str) or len(comment) > 1000:
        raise ValueError("请选择理解程度与困难环节，开放意见最多 1000 字且可以留空。")
    with store.connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        study = conn.execute("SELECT * FROM usability_tests WHERE id=?", (test_id,)).fetchone()
        if study:
            task = store.get(study["task_id"])
            if task.get("workflow_version", 1) >= 2:
                raise ValueError("新版工作台请使用独立体验反馈。")
        if not study or study["status"] == "active":
            raise ValueError("请先结束测试，再提交可选体验评价。")
        manual = conn.execute("SELECT protocol FROM study_manual_sessions WHERE task_id=?", (study["task_id"],)).fetchone()
        if manual:
            from src.workbench.manual_study import INTERVIEW_QUESTIONS
            keys = {k for k, _ in INTERVIEW_QUESTIONS}
            if not isinstance(interview, dict) or set(interview) != keys or any(not isinstance(v, str) or not v.strip() or len(v) > 2000 for v in interview.values()):
                raise ValueError("请回答手册中的三道结束访谈题；可以如实写“没有”或“不确定”，每题最多 2000 字。")
        elif interview is not None:
            raise ValueError("此记录使用原版简短问卷，请使用对应字段。")
        if not isinstance(difficulty_other, str) or len(difficulty_other) > 1000 or (difficulty == "其他" and manual and not difficulty_other.strip()):
            raise ValueError("选择其他困难时请补充说明，最多 1000 字。")
        payload = {"understanding": understanding, "difficulty": difficulty, "comment": comment, "submitted_at": _now(),
                   "schema_version": "manual_survey_v1" if manual else "short_survey_v1", "interview": interview or {},
                   "difficulty_other": difficulty_other.strip() if difficulty == "其他" else ""}
        answer = json.dumps(payload, ensure_ascii=False)
        conn.execute("UPDATE usability_tests SET questionnaire=? WHERE id=?", (answer, test_id))
        # Every submission is preserved even if a participant later corrects an answer.
        conn.execute("INSERT INTO events(task_id,created_at,name,payload) VALUES (?,?,?,?)",
                     (study["task_id"], _now(), "questionnaire_submitted", answer))


UX_STAGES = ["输入需求", "确认规则", "查看或修改模型", "查看结果", "没有明显困难", "其他"]


def submit_experience(store, test_id, ease, clarity, confusing_stage, had_problem, problem="", improvement=""):
    """Independent optional UX survey. Never confirms, revises or ends a task."""
    if (type(ease) is not int or ease not in range(1, 6) or type(clarity) is not int or clarity not in range(1, 6)
            or confusing_stage not in UX_STAGES or type(had_problem) is not bool):
        raise ValueError("请选择两项 1–5 分评价、困难环节及是否遇到问题。")
    if any(not isinstance(v, str) or len(v) > 2000 for v in (problem, improvement)):
        raise ValueError("文字反馈每项最多 2000 字。")
    if had_problem and not problem.strip():
        raise ValueError("请简单描述遇到的问题，方便组织者定位。")
    with store.connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM usability_tests WHERE id=?", (test_id,)).fetchone()
        if not row:
            raise ValueError("体验记录不存在，请先开始体验。")
        task = store.get(row["task_id"])
        if task.get("workflow_version", 1) < 2:
            raise ValueError("该记录使用历史版问卷，请通过原入口提交。")
        payload = {"schema_version": "workspace_ux_v2", "ease": ease, "clarity": clarity,
                   "confusing_stage": confusing_stage, "had_problem": had_problem,
                   "problem": problem.strip() if had_problem else "", "improvement": improvement.strip(), "submitted_at": _now(),
                   "feedback_model_version": task["model_version"], "feedback_task_status": task["status"]}
        answer = json.dumps(payload, ensure_ascii=False)
        conn.execute("UPDATE usability_tests SET questionnaire=? WHERE id=?", (answer, test_id))
        conn.execute("INSERT INTO events(task_id,created_at,name,payload) VALUES (?,?,?,?)",
                     (task["task_id"], _now(), "experience_feedback_submitted", answer))


def assess_discovery(store, test_id, label):
    from src.workbench.hosting import require_manager
    require_manager(store)
    if label not in ASSESSMENTS:
        raise ValueError("未知错误发现标签。")
    with store.connection() as conn:
        row = conn.execute("SELECT error_standard FROM usability_tests WHERE id=?", (test_id,)).fetchone()
        if not row or (label != "未评定" and not row["error_standard"].strip()):
            raise ValueError("请在开始测试前定义错误判定标准；没有标准不能评定错误发现。")
        conn.execute("UPDATE usability_tests SET assessment=? WHERE id=?", (label, test_id))


def delete_test(store, test_id):
    """Remove this dedicated test task and its data without touching ordinary tasks."""
    from src.workbench.hosting import require_manager
    require_manager(store)
    with store.connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT task_id FROM usability_tests WHERE id=?", (test_id,)).fetchone()
        if not row:
            return
        task_id = row["task_id"]
        task_row = conn.execute("SELECT snapshot FROM tasks WHERE id=?", (task_id,)).fetchone()
        task = json.loads(task_row["snapshot"])
        if task.get("usability_test_id") != test_id or not re.fullmatch(r"[a-f0-9]{32}", task_id):
            raise ValueError("测试关联不一致，无法删除普通任务。")
        if task["status"] in {"pending", "modeling", "revising", "solving", "executing"}:
            raise ValueError("任务仍在后台处理，请等待阶段结束后删除。")
        root = store.path.parent.resolve()
        files = [*(root / "traces").glob(f"{task_id}_v*.json*"), root / "worker_logs" / f"{task_id}.log"]
        run_dir = root / "runs" / task_id
        if any(not p.resolve().is_relative_to(root) for p in [*files, run_dir]):
            raise ValueError("测试文件路径异常，已停止删除。")
        for path in files:
            if path.is_file():
                path.unlink()
        if run_dir.is_dir():
            shutil.rmtree(run_dir)
        conn.execute("DELETE FROM events WHERE task_id=?", (task_id,))
        conn.execute("DELETE FROM usability_event_keys WHERE task_id=?", (row["task_id"],))
        manual = conn.execute("SELECT start_token FROM study_manual_sessions WHERE task_id=?", (task_id,)).fetchone()
        if manual:
            conn.execute("DELETE FROM study_manual_steps WHERE start_token=?", (manual["start_token"],))
            conn.execute("DELETE FROM study_manual_sessions WHERE task_id=?", (task_id,))
        conn.execute("DELETE FROM study_observations WHERE test_id=?", (test_id,))
        conn.execute("DELETE FROM usability_tests WHERE id=?", (test_id,))
        conn.execute("DELETE FROM hosted_invites WHERE task_id=?", (task_id,))
        conn.execute("DELETE FROM tasks WHERE id=?", (task_id,))


def _seconds(start, end):
    return max(0, (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()) if start and end else None


def test_records(store):
    with store.connection() as conn:
        if getattr(store, "participant_hash", None):
            task_id = store.invite(conn)["task_id"]
            studies = conn.execute("SELECT * FROM usability_tests WHERE task_id=?", (task_id,)).fetchall()
        else:
            studies = conn.execute("SELECT * FROM usability_tests ORDER BY started_at").fetchall()
    records = []
    for study in studies:
        row = dict(study)
        events = [e for e in store.events(row["task_id"]) if e["payload"].get("test_id") == row["id"]]
        first = lambda name: next((e["created_at"] for e in events if e["name"] == name), None)
        survey = json.loads(row["questionnaire"]) if row["questionnaire"] else {}
        review_start = first("model_review_opened")
        end = first("review_confirmed") or row["ended_at"]
        task = store.get(row["task_id"])
        from src.workbench.manual_study import manual_session, STEPS
        manual = manual_session(store, row["task_id"])
        with store.connection() as conn:
            observation = conn.execute("SELECT payload FROM study_observations WHERE test_id=?", (row["id"],)).fetchone() if not getattr(store, "participant_hash", None) else None
        notes = json.loads(observation["payload"]) if observation else {}
        record = {"test_id": row["id"], "participant_id": row["participant_id"], "case_id": row["case_id"],
                        "experience_channel": task.get("experience_channel", "historical_unlabeled"),
                        "task_id": row["task_id"], "model_version": row["ended_version"] if row["ended_version"] is not None else task["model_version"], "started_at": row["started_at"],
                        "ended_at": row["ended_at"], "status": row["status"], "elapsed_seconds": _seconds(row["started_at"], row["ended_at"]),
                        "review_seconds": _seconds(review_start, end), "model_confirmed": bool(first("review_confirmed")),
                        "feedback_submitted": bool(first("review_feedback_submitted")), "error_standard": row["error_standard"],
                        "assessment": row["assessment"], "questionnaire_submitted": bool(survey),
                        "understanding": survey.get("understanding", ""), "difficulty": survey.get("difficulty", ""),
                        "comment": survey.get("comment", ""), "questionnaire_version": survey.get("schema_version", "legacy_short" if survey else ""),
                        "questionnaire_submitted_at": survey.get("submitted_at", ""), "difficulty_other": survey.get("difficulty_other", ""),
                        "protocol": "workspace_v2" if task.get("workflow_version", 1) >= 2 else manual["protocol"] if manual else "legacy", "background": manual["background"] if manual else "",
                        **{k: survey.get(k, "") for k in ["ease", "clarity", "confusing_stage", "had_problem", "problem", "improvement", "feedback_model_version", "feedback_task_status"]},
                        "confusion": survey.get("interview", {}).get("confusion", ""), "work_use": survey.get("interview", {}).get("work_use", ""),
                        "one_improvement": survey.get("interview", {}).get("one_improvement", ""),
                        **{k: notes.get(k, "") for k in ["technical_issues", "severe_issue", "impact", "hypothesis"]}}
        step_rows = {r["step"]: r for r in manual["steps"]} if manual else {}
        for key, _, _ in STEPS:
            step = step_rows.get(key, {})
            observed = notes.get("steps", {}).get(key, {})
            record.update({f"{key}_submitted": bool(step.get("submitted_at")), f"{key}_answer": step.get("answer") or "",
                           f"{key}_elapsed_seconds": _seconds(step.get("opened_at"), step.get("submitted_at")),
                           f"{key}_model_version": step.get("model_version"), f"{key}_help_self_report": step.get("help_report") or "",
                           f"{key}_issue_state": step.get("issue_state") or "", f"{key}_issue": step.get("issue") or "", f"{key}_note_saved_at": step.get("saved_at") or "",
                           f"{key}_observer_status": observed.get("status", ""), f"{key}_observer_seconds": observed.get("seconds"),
                           f"{key}_observer_issue": observed.get("issue", "")})
        records.append(record)
    return records


def summarize_tests(records):
    count = len(records)
    done = sum(r["status"] == "completed" for r in records)
    assessed = [r for r in records if r["error_standard"] and r["assessment"] != "未评定"]
    times = [r["review_seconds"] for r in records if r["review_seconds"] is not None]
    return {"started": count, "completed": done, "completion_rate": done / count if count else None,
            "feedback_count": sum(r["feedback_submitted"] for r in records), "confirmation_count": sum(r["model_confirmed"] for r in records),
            "review_seconds": times, "review_mean_seconds": sum(times) / len(times) if times else None,
            "understanding": {x: sum(r["understanding"] == x for r in records) for x in UNDERSTANDING},
            "difficulty": {x: sum(r["difficulty"] == x for r in records) for x in DIFFICULTIES},
            "assessed_count": len(assessed), "discovery_count": sum(r["assessment"] == "正确发现" for r in assessed),
            "discovery_rate": sum(r["assessment"] == "正确发现" for r in assessed) / len(assessed) if assessed else None}


def export_csv(records):
    handle = io.StringIO(newline="")
    fields = ["test_id", "participant_id", "case_id", "task_id", "model_version", "started_at", "ended_at", "status", "elapsed_seconds",
              "review_seconds", "model_confirmed", "feedback_submitted", "assessment", "questionnaire_submitted", "understanding", "difficulty", "comment"]
    fields += ["protocol", "background", "error_standard", "questionnaire_version", "questionnaire_submitted_at", "difficulty_other", "confusion", "work_use", "one_improvement",
               "technical_issues", "severe_issue", "impact", "hypothesis"]
    fields += ["ease", "clarity", "confusing_stage", "had_problem", "problem", "improvement", "experience_channel", "feedback_model_version", "feedback_task_status"]
    for key in ["T1", "T2", "T3", "T4", "T5", "T6"]:
        fields += [f"{key}_{suffix}" for suffix in ["submitted", "answer", "elapsed_seconds", "model_version", "help_self_report", "issue_state", "issue", "note_saved_at", "observer_status", "observer_seconds", "observer_issue"]]
    writer = csv.DictWriter(handle, fields, extrasaction="ignore")
    writer.writeheader()
    for row in records:
        # Protect spreadsheet users from formula injection in free-text responses.
        writer.writerow({k: ("'" + v if isinstance(v, str) and v.startswith(("=", "+", "-", "@", "\t", "\r")) else v) for k, v in row.items() if k in fields})
    return handle.getvalue().encode("utf-8-sig")
