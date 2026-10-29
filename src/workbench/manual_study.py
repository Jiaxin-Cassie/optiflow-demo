"""Versioned six-task study protocol transcribed from the supplied user manual."""
import json

from src.workbench.explanations import valid_result, compare_versions
from src.workbench.store import now


PROTOCOL = "production_manual_v1"
BACKGROUNDS = ["不了解优化", "有少量了解", "熟悉优化"]
STEP_STATUS = ["未测试", "独立", "提示", "未完成"]
ISSUE_STATES = ["没有遇到问题", "遇到问题 / 不知道怎么继续"]
STEPS = [
    ("T1", "开始制定生产计划", "假设你是一家工厂的负责人，工厂生产 A、B 两种产品。现在你想知道：每天各生产多少件，才能赚到更多的钱？请试着使用这个网页，开始制定生产计划。"),
    ("T2", "看看系统理解得对不对", "系统已经根据工厂的情况整理了一份生产计划。请看看它理解的内容，然后用自己的话说明：它想帮工厂解决什么问题？工厂在生产时需要遵守哪些要求？"),
    ("T3", "检查有没有遗漏", "请再仔细看看，系统整理的内容有没有遗漏、理解错误或者不合理的地方？如果有，请说明；如果没有，也可以直接说没有。"),
    ("T4", "增加一条新要求", "现在工厂临时接到一个通知：A 产品每天最多只能生产 100 件。请试着把这个新要求告诉系统，让它重新制定计划。"),
    ("T5", "看看系统给出的建议", "现在请查看系统给出的生产建议。它建议 A、B 两种产品分别生产多少件？这样安排预计能赚多少钱？你觉得还有什么需要确认的吗？"),
    ("T6", "比较两次生产计划", "请看看增加新要求之前和之后的两份生产计划。它们有什么不同？如果老板问你“为什么要调整生产数量”，你会怎么向他解释？"),
]
INTERVIEW_QUESTIONS = [
    ("confusion", "刚才哪个地方最让你困惑？为什么？"),
    ("work_use", "你是否愿意在真实工作中使用？需要哪些条件？"),
    ("one_improvement", "如果只能改进一处，你希望改哪里？"),
]
SCHEMA = """
CREATE TABLE IF NOT EXISTS study_manual_sessions (
 start_token TEXT PRIMARY KEY, participant_id TEXT NOT NULL, case_id TEXT NOT NULL,
 task_id TEXT UNIQUE, protocol TEXT NOT NULL, background TEXT NOT NULL, started_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS study_manual_steps (
 start_token TEXT NOT NULL, step TEXT NOT NULL, opened_at TEXT NOT NULL, submitted_at TEXT,
 model_version INTEGER, answer TEXT, help_report TEXT,
 PRIMARY KEY(start_token,step)
);
CREATE TABLE IF NOT EXISTS study_observations (
 test_id TEXT PRIMARY KEY, payload TEXT NOT NULL, updated_at TEXT NOT NULL
);
"""


def begin_manual(store, background):
    invite = store.invite()
    if invite["case_id"] != "production" or background not in BACKGROUNDS:
        raise ValueError("六任务手册使用工厂生产案例，请选择你的优化背景。")
    with store.connection() as conn:
        conn.execute("INSERT OR IGNORE INTO study_manual_sessions VALUES (?,?,?,?,?,?,?)",
                     (invite["start_token"], invite["participant_id"], invite["case_id"], invite["task_id"], PROTOCOL, background, now()))
        conn.execute("INSERT OR IGNORE INTO study_manual_steps(start_token,step,opened_at) VALUES (?,?,?)",
                     (invite["start_token"], "T1", now()))
    return manual_session(store)


def manual_session(store, task_id=None):
    with store.connection() as conn:
        if getattr(store, "participant_hash", None):
            invite = store.invite(conn)
            if task_id is not None:
                store.assert_access(task_id, conn)
            row = conn.execute("SELECT * FROM study_manual_sessions WHERE start_token=?", (invite["start_token"],)).fetchone()
        elif task_id:
            store.get(task_id)
            row = conn.execute("SELECT * FROM study_manual_sessions WHERE task_id=?", (task_id,)).fetchone()
        else:
            return None
        if not row:
            return None
        session = dict(row)
        session["steps"] = [dict(r) for r in conn.execute("SELECT * FROM study_manual_steps WHERE start_token=? ORDER BY step", (row["start_token"],))]
    return session


def current_step(session):
    done = {r["step"] for r in session["steps"] if r["submitted_at"]}
    return next((s for s in STEPS if s[0] not in done), None)


def baseline(task):
    return next((v for v in [*task.get("versions", []), task] if v.get("model_version") == 1 and valid_result(v)), None)


def require_baseline_before_revision(store, task):
    session = manual_session(store, task["task_id"])
    if not session:
        return
    from src.workbench.usability import study_for_task
    study = study_for_task(store, task["task_id"])
    if study and study["status"] != "active":
        raise ValueError("本次测试已结束，保留提交时的模型与问卷；如需再次测试请联系组织者。")
    if not baseline(task):
        raise ValueError("为比较前后两份计划，请先确认初始模型、求解并保留第一版结果，再补充新要求。")


def _viewed(store, task, name):
    return any(e["name"] == name and e["payload"].get("model_version") == task["model_version"] for e in store.events(task["task_id"]))


def step_requirement(store, task, step):
    if not task:
        return "请先在工作台中创建工厂生产任务。"
    if step == "T1":
        return None
    if step in {"T2", "T3"}:
        return None if task.get("model") and _viewed(store, task, "model_review_opened") else "请先打开模型查看与确认页面，阅读系统整理的业务内容。"
    if step == "T4":
        if not baseline(task):
            return "先确认并求解初始模型，保留第一版方案，再补充新要求。"
        has_limit = any(c.get("coefficients") == {"A": 1} and c.get("relation") == "<=" and c.get("rhs") == 100
                        for c in (task.get("model") or {}).get("constraints", []))
        return None if task["model_version"] > 1 and has_limit else "请在模型页面提交 A 每天最多生产 100 件的新要求，并等待新模型生成。"
    if step == "T5":
        return None if task["model_version"] > 1 and valid_result(task) and _viewed(store, task, "result_viewed") else "请确认修改后的模型、求解，并打开当前版本的结果。"
    if step == "T6":
        old = baseline(task)
        if not old or task["model_version"] <= 1 or not compare_versions(old, task)["comparable"]:
            return "需要初始方案和修改后方案都已确认、求解并通过数值检查。"
        return None if _viewed(store, task, "comparison_viewed") else "请打开“前后方案对比”页面，查看两份方案后再记录你的解释。"
    raise ValueError("未知测试步骤。")


def _check_note(answer, help_report, issue_state, issue):
    if not isinstance(answer, str) or len(answer) > 2000 or not isinstance(issue, str) or len(issue) > 2000:
        raise ValueError("回答与问题说明每项最多 2000 字。")
    if help_report not in {None, "未获得提示", "获得提示"}:
        raise ValueError("请选择是否得到他人提示。")
    if issue_state not in {None, *ISSUE_STATES}:
        raise ValueError("请选择本步是否遇到问题。")
    if issue_state == ISSUE_STATES[1] and not issue.strip():
        raise ValueError("请简单说明卡在哪里，例如不知道哪个按钮可以继续。")


def save_step_note(store, step, answer="", help_report=None, *, issue_state=None, issue=""):
    """A blocked participant can save a problem without falsely finishing a step."""
    _check_note(answer, help_report, issue_state, issue)
    session = manual_session(store)
    if not session or not current_step(session) or current_step(session)[0] != step:
        raise ValueError("当前步骤已变化，请刷新后再保存。")
    with store.connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        invite = store.invite(conn)
        if invite["start_token"] != session["start_token"]:
            raise PermissionError("无法修改其他参与者的记录。")
        cursor = conn.execute("UPDATE study_manual_steps SET answer=?,help_report=?,issue_state=?,issue=?,saved_at=? WHERE start_token=? AND step=? AND submitted_at IS NULL",
                              (answer.strip(), help_report, issue_state, issue.strip() if issue_state != ISSUE_STATES[0] else "", now(), session["start_token"], step))
        if not cursor.rowcount:
            raise ValueError("该步骤已经提交，请刷新。")


def submit_step(store, step, answer="", help_report="未获得提示", *, expected_version, issue_state=None, issue=""):
    _check_note(answer, help_report, issue_state, issue)
    session = manual_session(store)
    if not session or not current_step(session) or current_step(session)[0] != step:
        raise ValueError("测试步骤已变化，请刷新后继续；不会重复记录完成。")
    if not isinstance(answer, str) or len(answer) > 2000 or (step in {"T2", "T3", "T5", "T6"} and not answer.strip()):
        raise ValueError("请用自己的话记录本步回答；没有发现问题时也可以如实说明。最多 2000 字。")
    if help_report not in {"未获得提示", "获得提示"}:
        raise ValueError("请选择是否得到他人提示。")
    task = store.get(session["task_id"]) if session["task_id"] else None
    if not task or task["model_version"] != expected_version:
        raise ValueError("当前模型版本已变化，请重新查看后再记录本步。")
    error = step_requirement(store, task, step)
    if error:
        raise ValueError(error)
    with store.connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if hasattr(store, "assert_access"):
            store.assert_access(task["task_id"], conn)
        saved = json.loads(conn.execute("SELECT snapshot FROM tasks WHERE id=?", (task["task_id"],)).fetchone()["snapshot"])
        if saved["model_version"] != expected_version or saved["status"] != task["status"]:
            raise ValueError("任务正在变化，请刷新后再记录。")
        cursor = conn.execute("UPDATE study_manual_steps SET submitted_at=?,model_version=?,answer=?,help_report=?,issue_state=?,issue=?,saved_at=? WHERE start_token=? AND step=? AND submitted_at IS NULL",
                              (now(), expected_version, answer.strip(), help_report, issue_state, issue.strip() if issue_state != ISSUE_STATES[0] else "", now(), session["start_token"], step))
        if not cursor.rowcount:
            raise ValueError("该步骤已记录，请刷新。")
        conn.execute("INSERT INTO events(task_id,created_at,name,payload) VALUES (?,?,?,?)",
                     (task["task_id"], now(), "manual_step_submitted", json.dumps({"protocol": PROTOCOL, "step": step, "model_version": expected_version}, ensure_ascii=False)))
        index = [s[0] for s in STEPS].index(step)
        if index < 5:
            conn.execute("INSERT OR IGNORE INTO study_manual_steps(start_token,step,opened_at) VALUES (?,?,?)", (session["start_token"], STEPS[index+1][0], now()))


def record_comparison(store, task):
    if manual_session(store, task["task_id"]) and baseline(task) and task["model_version"] > 1:
        if compare_versions(baseline(task), task)["comparable"]:
            from src.workbench.usability import record_view
            record_view(store, task["task_id"], "comparison_viewed")


def observation(store, test_id):
    from src.workbench.hosting import require_manager
    require_manager(store)
    with store.connection() as conn:
        row = conn.execute("SELECT payload FROM study_observations WHERE test_id=?", (test_id,)).fetchone()
    return json.loads(row["payload"]) if row else {}


def enrollment_records(store):
    """Include people who started T1 but have not created a task yet."""
    from src.workbench.hosting import require_manager
    require_manager(store)
    with store.connection() as conn:
        rows = conn.execute("SELECT s.participant_id,s.protocol,s.background,s.started_at,s.task_id,t.issue_state AS T1_issue_state,t.issue AS T1_issue,t.saved_at AS T1_note_saved_at FROM study_manual_sessions s LEFT JOIN study_manual_steps t ON t.start_token=s.start_token AND t.step='T1' ORDER BY s.started_at").fetchall()
    return [dict(r) for r in rows]


def save_observation(store, test_id, payload):
    from src.workbench.hosting import require_manager
    require_manager(store)
    if not isinstance(payload, dict) or set(payload) != {"steps", "technical_issues", "severe_issue", "impact", "hypothesis"}:
        raise ValueError("观察记录字段不完整。")
    if not isinstance(payload["steps"], dict) or set(payload["steps"]) != {s[0] for s in STEPS}:
        raise ValueError("需要六步观察记录。")
    for value in payload["steps"].values():
        if (not isinstance(value, dict) or set(value) != {"status", "seconds", "issue"} or value["status"] not in STEP_STATUS
                or value["seconds"] is not None and (isinstance(value["seconds"], bool) or not isinstance(value["seconds"], (int,float)) or not 0 <= value["seconds"] <= 86400)
                or not isinstance(value["issue"], str) or len(value["issue"]) > 2000):
            raise ValueError("请检查步骤完成情况、耗时和问题说明。")
    if any(not isinstance(payload[k], str) or len(payload[k]) > 3000 for k in ["technical_issues", "severe_issue", "impact", "hypothesis"]):
        raise ValueError("观察者说明每项最多 3000 字。")
    with store.connection() as conn:
        study = conn.execute("SELECT task_id FROM usability_tests WHERE id=?", (test_id,)).fetchone()
        if not study:
            raise ValueError("测试记录不存在。")
        conn.execute("INSERT INTO study_observations VALUES (?,?,?) ON CONFLICT(test_id) DO UPDATE SET payload=excluded.payload,updated_at=excluded.updated_at",
                     (test_id, json.dumps(payload,ensure_ascii=False,allow_nan=False), now()))
        conn.execute("INSERT INTO events(task_id,created_at,name,payload) VALUES (?,?,?,?)", (study["task_id"], now(), "study_observer_updated", json.dumps(payload,ensure_ascii=False,allow_nan=False)))
