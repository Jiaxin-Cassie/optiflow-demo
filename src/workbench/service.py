"""Task API: prepare -> human confirmation -> solve -> independently validate."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from src.agents.evaluator import Evaluator
from src.workbench.cases import CASES, case_model
from src.workbench.model import validate_model, numerical_checks, ModelError
from src.workbench.store import TaskStore, ROOT, now


STAGES = [("parse", "需求解析"), ("retrieve", "Skill 检索"), ("model", "数学建模"),
          ("code", "代码生成"), ("execute", "执行修复"), ("validate", "结果校验")]
ACTIVE_STATUSES = {"pending", "modeling", "revising", "solving"}


def model_hash(model):
    return hashlib.sha256(json.dumps(model, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()).hexdigest()


def _empty_validation():
    return {"numerical_feasibility": "not_checked", "semantic_correctness": "not_verified", "checks": []}


def _usage(task, adapter, phase):
    if adapter is not None and hasattr(adapter, "usage_summary"):
        task.setdefault("usage", {})[phase] = adapter.usage_summary()


def create_task(problem_text, selected_skills=None, *, mode="live", case_id=None,
                title="未命名优化任务", category="其他", store=None, usability_context=None, workflow_version=1):
    store = store or TaskStore()
    if not isinstance(problem_text, str) or not 10 <= len(problem_text.strip()) <= 16000:
        raise ModelError("请输入 10–16000 字的业务需求。")
    if mode not in {"live", "case"}:
        raise ModelError("未知运行模式。")
    if workflow_version not in {1, 2}:
        raise ModelError("未知工作流版本。")
    if selected_skills is not None and (not isinstance(selected_skills, list) or any(not isinstance(s, str) for s in selected_skills)):
        raise ModelError("selected_skills 必须为名称列表或 None。")
    if mode == "case":
        case_model(case_id, problem_text.strip())
    task = {"task_id": uuid4().hex, "title": (title.strip() or "未命名优化任务")[:80], "category": category,
            "mode": mode, "case_id": case_id, "problem_text": problem_text.strip(), "effective_text": problem_text.strip(),
            "selected_skills": selected_skills, "created_at": now(), "status": "pending", "model_version": 0,
            "feedback": [], "versions": [], "stages": [{"key": k, "name": n, "status": "pending"} for k, n in STAGES],
            "model": None, "solver": {}, "validation": _empty_validation(), "activated_skills": [], "selected_references": [],
            "human_review": {"status": "pending", "version": None}, "failure": None, "badcase_status": "待处理",
            "workflow_version": workflow_version, "business_review": {"status": "pending", "version": None}}
    if usability_context:
        task["usability_test_id"] = usability_context["id"]
        task["experience_channel"] = ("public_demo" if getattr(store, "public_demo", False)
                                      else "invited" if getattr(store, "participant_hash", None) else "local")
    store.save(task, "task_created", {"mode": mode, "category": category}, usability_context=usability_context)
    return task


def _stage(task, key, action, store, detail):
    stage = next(s for s in task["stages"] if s["key"] == key)
    stage.update(status="running", started_at=now(), detail=detail)
    store.save(task, "stage_started", {"stage": key, "version": task["model_version"]})
    started = perf_counter()
    try:
        result = action()
    except Exception:
        stage.update(status="failed", elapsed_seconds=perf_counter() - started, finished_at=now())
        raise
    stage.update(status="completed", elapsed_seconds=perf_counter() - started, finished_at=now())
    store.save(task, "stage_completed", {"stage": key, "elapsed_seconds": stage["elapsed_seconds"]})
    return result


def _snapshot_trace(task, store):
    from src.storage import atomic_json
    path = store.path.parent / "traces" / f"{task['task_id']}_v{task['model_version']}.json"
    atomic_json(path, task)


def _failed(task, exc, store):
    from src.errors import GenerationFailure
    failed_stage = next((s["key"] for s in task["stages"] if s["status"] == "failed"), "setup")
    # Provider messages, URLs, config and credentials must never enter product errors.
    messages = {"parse": "需求解析失败，请检查模型服务配置或稍后重试。",
                "retrieve": "Skill 检索失败，请检查知识库或稍后重试。",
                "model": "建模失败，可能是输入不完整、超出 LP/MILP 范围或模型结构不合规。",
                "code": "代码生成失败，请重新建模后再确认。",
                "execute": "求解执行失败，请检查依赖、模型与求解预算。",
                "validate": "结果校验失败，请查看模型和决策量。",
                "setup": "任务初始化失败，请检查依赖与 src/config.py 中的服务配置。"}
    task["status"] = "failed"
    kind = type(exc).__name__
    if isinstance(exc, GenerationFailure) and exc.kind in {
        "output_truncated", "empty_response", "invalid_fef_structure", "missing_client", "empty_code",
        "APIConnectionError", "APITimeoutError", "RateLimitError", "InternalServerError",
        "AuthenticationError", "PermissionDeniedError", "BadRequestError", "QuotaExceededError",
    }:
        kind = exc.kind
    task["failure"] = {"stage": failed_stage, "kind": kind,
                       "message": str(exc) if isinstance(exc, ModelError) else messages[failed_stage]}
    if kind == "output_truncated":
        task["failure"]["message"] = "模型服务输出达到长度上限，请缩小问题范围后重新建模。"
    for stage in task["stages"]:
        if stage["status"] == "pending":
            stage["status"] = "blocked"
    store.save(task, "task_failed", task["failure"])
    _snapshot_trace(task, store)
    return task


def prepare_task(task_id, *, store=None, adapter=None):
    store = store or TaskStore()
    task = store.claim(task_id, {"pending", "revising"}, "modeling")
    own_adapter = False
    try:
        if task["mode"] == "live":
            if adapter is None:
                from src.workbench.adapter import AgentAdapter
                adapter = AgentAdapter()
                own_adapter = True
            profile = _stage(task, "parse", lambda: adapter.profile(task["effective_text"]), store, "提取业务目标、资源限制和缺失信息")
            activated, references = _stage(task, "retrieve", lambda: adapter.route(task, profile), store, "检索并筛选与当前业务相关的建模技能")
            task["profile"] = profile.model_dump()
            task["activated_skills"] = [s.model_dump() for s in activated]
            task["selected_references"] = [r.model_dump() for r in references]
            model, fef = _stage(task, "model", lambda: adapter.formulate(task, profile, activated, references), store, "生成带原文依据、边界与假设的结构化模型")
            task["fef_text"] = fef
        else:
            _stage(task, "parse", lambda: None, store, "内置案例：读取已标注业务要素，不调用 LLM")
            _stage(task, "retrieve", lambda: None, store, "内置案例：跳过实时 Skill 检索，不调用 LLM")
            model = _stage(task, "model", lambda: case_model(task["case_id"], task["problem_text"], task["feedback"]), store, "加载案例模型并应用支持的用户约束")
        task["model"] = validate_model(model, task["effective_text"])
        _usage(task, adapter, "modeling")
        task["model_version"] += 1
        task["model_hash"] = model_hash(task["model"])
        task["status"] = "awaiting_confirmation"
        store.save(task, "model_ready", {"version": task["model_version"], "model_hash": task["model_hash"]})
        _snapshot_trace(task, store)
        return task
    except Exception as exc:
        _usage(task, adapter, "modeling")
        return _failed(task, exc, store)
    finally:
        if own_adapter:
            adapter.close()


def run_optimization_task(problem_text: str, selected_skills: list[str] | None = None, **kwargs) -> dict:
    """Build a reviewable model and STOP before solving. Never confirms on behalf of users."""
    store = kwargs.pop("store", None) or TaskStore()
    adapter = kwargs.pop("adapter", None)
    task = create_task(problem_text, selected_skills, store=store, **kwargs)
    return prepare_task(task["task_id"], store=store, adapter=adapter)


def revise_task(task_id, feedback, *, expected_version, store=None, defer=False, adapter=None):
    store = store or TaskStore()
    if not isinstance(feedback, str) or not 3 <= len(feedback.strip()) <= 2000:
        raise ModelError("补充需求需要 3–2000 字。")
    task = store.get(task_id)
    from src.workbench.manual_study import require_baseline_before_revision
    if task.get("workflow_version", 1) < 2:
        require_baseline_before_revision(store, task)
    if len(task["effective_text"]) + len(feedback) > 16000:
        raise ModelError("累计需求超过 16000 字，请新建任务整理需求。")
    if task["mode"] == "case":
        case_model(task["case_id"], task["problem_text"], [*task["feedback"], feedback.strip()])
    task = store.claim(task_id, {"awaiting_confirmation", "completed", "failed", "no_solution", "needs_attention"}, "revising", expected_version)
    if task.get("model"):
        task["versions"].append({k: deepcopy(task.get(k)) for k in
            ("model_version", "model", "model_hash", "solver", "validation", "human_review", "business_review", "workflow_version", "effective_text", "failure", "revision_note")})
    task["revision_note"] = feedback.strip()
    task["feedback"].append(feedback.strip())
    task["effective_text"] = task["problem_text"] + "\n\n用户补充需求：\n" + "\n".join(task["feedback"])
    task.update(model=None, solver={}, validation=_empty_validation(), failure=None, usage={},
                human_review={"status": "pending", "version": None},
                business_review={"status": "pending", "version": None},
                stages=[{"key": k, "name": n, "status": "pending"} for k, n in STAGES])
    store.save(task, "revision_requested", {"feedback": feedback.strip(), "previous_version": expected_version})
    return task if defer else prepare_task(task_id, store=store, adapter=adapter)


def confirm_task(task_id, *, expected_version, store=None, defer=False, adapter=None):
    store = store or TaskStore()
    current = store.get(task_id)
    if not current.get("model"):
        raise ModelError("尚无可确认的模型。")
    validate_model(current["model"], current["effective_text"])
    if current["model"].get("missing_inputs"):
        raise ModelError("请先补充模型标出的缺失输入，再重新建模。")
    if model_hash(current["model"]) != current["model_hash"]:
        raise ModelError("模型内容发生变化，请重新建模后确认。")
    from src.workbench.flow import require_business
    task = store.claim(task_id, {"awaiting_confirmation"}, "solving", expected_version, check=require_business)
    task["human_review"] = {"status": "confirmed", "version": task["model_version"],
                            "model_hash": task["model_hash"], "confirmed_at": now(),
                            "scope": "用户确认当前模型的业务含义；不构成数学正确性证明。"}
    store.save(task, "model_confirmed", task["human_review"])
    return task if defer else solve_task(task_id, store=store, adapter=adapter)


def solve_task(task_id, *, store=None, adapter=None):
    store = store or TaskStore()
    # A second atomic claim prevents duplicate worker launches for the same confirmation.
    task = store.claim(task_id, {"solving"}, "executing")
    own_adapter = False
    try:
        from src.workbench.flow import require_business
        require_business(task)
        if (task["human_review"].get("model_hash") != model_hash(task["model"])
                or task["human_review"].get("version") != task["model_version"]
                or task["human_review"].get("status") != "confirmed"):
            raise ModelError("确认记录与模型不一致，已阻止求解。")
        directory = store.path.parent / "runs" / task_id / f"v{task['model_version']}"
        directory.mkdir(parents=True, exist_ok=True)
        if task["mode"] == "live":
            if adapter is None:
                from src.workbench.adapter import AgentAdapter
                adapter = AgentAdapter()
                own_adapter = True
            task["code_artifact"] = _stage(task, "code", lambda: adapter.generate_artifact(task, directory), store,
                                            "生成审阅代码并检查语法；经确认的模型由受控解释器求解")
        else:
            _stage(task, "code", lambda: None, store, "内置案例：构建已确认模型的受控求解入口，不调用 Code Agent")
        # Python source is composed solely by trusted code, with data serialized via repr.
        # No eval, exec, generated expression or generated import is accepted.
        entry = directory / "trusted_solver.py"
        entry.write_text("import sys\nsys.path.insert(0, " + repr(str(ROOT)) + ")\n"
                         "from src.workbench.solver import emit_result\n"
                         "emit_result(" + repr(task["model"]) + ", " + repr(task["effective_text"]) + ")\n", encoding="utf-8")
        evaluator = Evaluator(code_timeout=30)
        execution = _stage(task, "execute", lambda: evaluator.execute(entry), store, "独立子进程解释模型；HiGHS 15 秒预算，进程 30 秒超时")
        execution = evaluator.assess(execution, None)
        task["solver"] = {"status": execution.solver_status_normalized, "raw_status": execution.solver_status,
                          "objective_value": execution.objective_value, "solution": execution.variable_values,
                          "backend": execution.solver_record.get("backend", "unknown"),
                          "runtime_seconds": evaluator.last_execution_seconds, "code_executable": execution.code_executable}
        if not execution.code_executable or execution.solver_status_normalized in {"InvalidResult", "Unknown"}:
            # Do not persist stderr from a process into the user-facing record.
            next(s for s in task["stages"] if s["key"] == "execute")["status"] = "failed"
            raise RuntimeError("Trusted solver failed")
        validation = _stage(task, "validate", lambda: numerical_checks(task["model"], execution.variable_values, execution.objective_value), store,
                            "独立重算全部约束、变量边界、整数性与目标值")
        task["validation"] = {**validation, "semantic_correctness": "not_verified"}
        _usage(task, adapter, "solving")
        status = task["solver"]["status"]
        task["status"] = ("completed" if status == "Optimal" and validation["numerical_feasibility"] == "passed"
                          else "no_solution" if status in {"Infeasible", "Unbounded", "InfeasibleOrUnbounded"}
                          else "needs_attention")
        if task["status"] != "completed":
            task["failure"] = {"stage": "execute" if task["status"] == "no_solution" else "validate",
                               "kind": status if task["status"] == "no_solution" else "result_requires_review",
                               "message": "未获得可用的最优方案，请检查需求冲突、求解状态和数值检查。"}
        store.save(task, "task_finished", {"status": task["status"], "solver_status": status})
        _snapshot_trace(task, store)
        return task
    except Exception as exc:
        _usage(task, adapter, "solving")
        return _failed(task, exc, store)
    finally:
        if own_adapter:
            adapter.close()


ACTIVE_STATUSES.add("executing")


def report_markdown(task):
    model, solver = task.get("model") or {}, task.get("solver") or {}
    from src.workbench.model import expression
    lines = [f"# OptiFlow · {task['title']}", f"任务：{task['task_id']} · 模型版本 v{task['model_version']}",
             f"模式：{'内置案例，本地真实求解' if task['mode'] == 'case' else '原 Agent 实时建模'}", "", "## 业务需求", task["effective_text"],
             "", "## 决策变量"]
    for var in model.get("variables", []):
        lines.append(f"- {var['name']}：{var.get('label', '')}；{var['domain']}；下界 {var.get('lower')}，上界 {var.get('upper')}")
    if model:
        obj = model["objective"]
        lines.extend(["", "## 目标", f"{obj['sense']} {expression(obj['coefficients'])} + {obj.get('constant', 0)}", "", "## 约束与依据"])
        for c in model["constraints"]:
            lines.append(f"- {c.get('label', c['id'])}：{expression(c['coefficients'])} {c['relation']} {c['rhs']}；依据：{c.get('source') or c.get('assumption')}")
        lines.extend(["", "## 建模假设", *[f"- {x}" for x in model.get("assumptions", [])]])
    lines.extend(["", "## 求解与检查", f"求解器状态：{solver.get('status', '未求解')}",
                  f"目标值：{solver.get('objective_value')}", f"决策量：{json.dumps(solver.get('solution', {}), ensure_ascii=False)}",
                  f"数值可行性：{task['validation']['numerical_feasibility']}",
                  f"人工复核：{task['human_review']['status']}", "语义正确性：未独立验证；人工确认不等于数学正确性证明。", "", "## 约束残差"])
    for c in task["validation"].get("checks", []):
        lines.append(f"- {c['name']}：残差 {c['residual']:.6g}；违反量 {c['violation']:.6g}；通过：{c['passed']}")
    return "\n\n".join(lines)

