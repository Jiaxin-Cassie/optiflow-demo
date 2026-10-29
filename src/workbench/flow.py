"""Version-bound business approval shared by UI and task execution."""
import json

from src.workbench.model import ModelError
from src.workbench.store import now


STEPS = ["描述需求", "确认规则", "检查模型", "查看方案"]


def business_confirmed(task):
    from src.workbench.service import model_hash
    review = task.get("business_review") or {}
    return bool(task.get("model") and review.get("status") == "confirmed"
                and review.get("version") == task["model_version"]
                and review.get("model_hash") == task.get("model_hash") == model_hash(task["model"]))


def require_business(task):
    if task.get("workflow_version", 1) >= 2 and not business_confirmed(task):
        raise ModelError("请先确认当前版本的业务目标和限制，再检查模型并计算。")


def confirm_business(task_id, *, expected_version, store):
    from src.workbench.service import model_hash
    with store.connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if hasattr(store, "assert_access"):
            store.assert_access(task_id, conn)
        row = conn.execute("SELECT snapshot FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not row:
            raise ModelError("任务不存在。")
        task = json.loads(row["snapshot"])
        if task["status"] != "awaiting_confirmation" or task["model_version"] != expected_version:
            raise ModelError("任务状态或模型版本已变化，请刷新后重新检查。")
        if not task.get("model") or task["model_hash"] != model_hash(task["model"]):
            raise ModelError("模型已变化，请重新建模。")
        from src.workbench.model import validate_model
        validate_model(task["model"], task["effective_text"])
        if task["model"].get("missing_inputs"):
            raise ModelError("请先补充缺失的业务信息。")
        task["workflow_version"] = 2
        task["business_review"] = {"status": "confirmed", "version": expected_version,
                                   "model_hash": task["model_hash"], "confirmed_at": now()}
        store._save(conn, task)
        conn.execute("INSERT INTO events(task_id,created_at,name,payload) VALUES (?,?,?,?)",
                     (task_id, now(), "business_confirmed", json.dumps(task["business_review"], ensure_ascii=False)))
    return task


def current_step(task):
    if not task or task["status"] == "pending":
        return 0
    if task["status"] in {"solving", "executing", "completed", "no_solution", "needs_attention"}:
        return 3
    return 2 if business_confirmed(task) else 1


def step_blocker(task, step):
    if step == 0:
        return None
    if not task or not task.get("model"):
        return "请先提交业务需求，等待模型生成。"
    if step == 3 and task.get("workflow_version", 1) < 2 and task["status"] == "completed":
        return None  # Historical results retain their original review protocol.
    if step >= 2 and not business_confirmed(task):
        return "请先在“确认规则”中确认当前版本的业务目标和限制。"
    if step == 3 and task.get("human_review", {}).get("status") != "confirmed":
        return "请先检查模型，点击“确认模型并计算方案”。"
    return None
