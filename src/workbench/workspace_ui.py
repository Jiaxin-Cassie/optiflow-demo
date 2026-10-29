"""Guidance, four business stages and independent experience feedback."""
import html
import json
from pathlib import Path
from uuid import uuid4

import streamlit as st

from src.workbench.cases import CASES, parse_case_feedback
from src.workbench.charts import quantity_chart_html
from src.workbench.explanations import model_review_data, decision_summary, fmt
from src.workbench.flow import STEPS, business_confirmed, confirm_business, current_step, step_blocker
from src.workbench.hosting import start_invited_test, hosted_mode
from src.workbench.review_ui import alignment_panel, decision_panel
from src.workbench.review import model_alignment
from src.workbench.service import ACTIVE_STATUSES, create_task, confirm_task, revise_task, report_markdown
from src.workbench.usability import (UX_STAGES, study_for_task, record_view, finish_test, submit_experience)


def navigate(view, step=None):
    st.session_state["of_view"] = view
    if step is not None:
        st.session_state["of_step"] = step
    st.session_state.pop("of_modify", None)


def move(view, step=None):
    navigate(view, step)
    st.rerun()


def new_demo():
    st.session_state.pop("demo_visitor_secret", None)
    st.session_state.pop("task_id", None)
    navigate("guide", 0)


def _task(store):
    identifier = st.session_state.get("task_id")
    try:
        return store.get(identifier) if identifier else None
    except (ValueError, PermissionError):
        st.session_state.pop("task_id", None)
        return None


def _title(title, hint):
    st.title(title)
    st.write(hint)


def _guide(task, participant):
    st.html('<div class="of-kicker">OptiFlow / 产品导引</div>')
    _title("用一句话描述问题，让 AI 帮你制定更合理的方案。", "从业务需求到可检查的决策，无需先掌握数学建模知识。")
    st.button("继续我的方案" if task else "开始体验", type="primary", on_click=navigate,
              args=("workspace", current_step(task)), key="of-start")
    if not participant:
        if st.button("试试生产计划示例"):
            st.session_state["of_input_mode"] = "内置案例"
            st.session_state["of_case"] = "production"
            move("workspace", 0)
    example_case = st.session_state.get("of_guide_case", "production")
    example = CASES.get(example_case, CASES["production"])["description"]
    st.caption("示例业务问题："+example)
    with st.container():
        for col, index, title, text in zip(st.columns(4), range(1, 5), STEPS,
                ["说清目标、资源和限制。", "核对系统理解是否完整。", "检查规则及建模假设。", "查看建议、收益和检查结果。"]):
            col.html(f'<div class="of-step"><span>{index}</span><b>{title}</b><p>{text}</p></div>')
    st.caption("先体验产品，再自愿填写体验反馈。反馈不会改变你的模型，也不影响继续使用。")
    with st.expander("使用前可以了解什么？"):
        st.write("你可以随时返回查看规则、修改需求或重新计算。模型生成后会暂停，等你确认，再求解。")
        st.write("内置案例读取预置模型并真实计算；实时建模使用已配置的模型服务。两种来源始终明确标注。")
        st.write("求解成功表示对当前模型找到了方案；数值检查和业务含义复核分别记录，不代表业务结果已被证明正确。")


def _input(store, task, participant, queue):
    demo = bool(getattr(store, "public_demo", False))
    _title("你想解决什么业务问题？", "描述目标、可用资源和必须遵守的要求。系统先整理规则，暂不计算。")
    if task:
        st.info("当前已有一个任务。返回后续步骤可以继续；补充当前任务的要求，请使用“需要修改”。")
        with st.expander("查看已提交的业务需求", expanded=True):
            st.write(task["effective_text"])
        st.button("继续当前任务", type="primary", on_click=navigate, args=("workspace", current_step(task)))
        if not participant or demo:
            if st.button("开始新的演示" if demo else "另建一个任务"):
                if demo:
                    new_demo()
                    st.rerun()
                st.session_state.pop("task_id", None)
                move("workspace", 0)
        return
    with st.container(border=True, key="of-input-card"):
        selected_skills = None
        if participant and not demo:
            case = CASES[store.invite()["case_id"]]
            st.subheader(case["title"])
            st.write(case["text"])
            st.caption("内置案例 · 使用已标注模型，不调用实时 AI；后续确认和求解为真实操作。")
            if st.button("分析这个业务需求", type="primary"):
                try:
                    created = start_invited_test(store)
                    st.session_state["task_id"] = created["task_id"]
                    if created["status"] == "pending":
                        queue(created, "prepare")
                    move("workspace", current_step(created) if created.get("model") else 1)
                except (ValueError, PermissionError) as exc:
                    st.error(str(exc))
            return
        mode = "内置案例" if demo else st.radio("需求来源", ["内置案例", "实时建模"], horizontal=True, key="of_input_mode")
        if mode == "内置案例":
            case_id = st.selectbox("选择业务案例", list(CASES), format_func=lambda k: CASES[k]["title"], key="of_case")
            case = CASES[case_id]
            st.text_area("业务需求（案例原文）", case["text"], height=180, disabled=True, key="of-case-text-"+case_id)
            problem, title, category = case["text"], case["title"], case["category"]
            st.caption("预置模型 + 本地真实求解。支持补充单个数量上下限；任意新问题请选择实时建模。")
        else:
            title = st.text_input("任务名称", value="我的业务方案", max_chars=80)
            category = st.selectbox("业务类别", ["生产计划", "资源分配", "人员排班", "物流运输", "其他"])
            problem = st.text_area("描述业务情况", height=200, max_chars=16000,
                placeholder="例如：需要安排哪些产品或人员？希望提高什么或降低什么？有哪些资源上限或最低要求？")
            case_id = None
            st.caption("AI 实时建模 · 使用已配置服务，生成过程和失败均按实际记录展示。")
            with st.expander("高级：选择建模技能（可选）"):
                from src.skill_loader import load_skills
                from src.workbench.store import ROOT
                automatic = st.checkbox("自动检索相关技能", value=True)
                if not automatic:
                    selected_skills = st.multiselect("候选技能（留空表示不注入知识）", [s.name for s in load_skills(ROOT / "skill_library")], placeholder="选择建模技能")
        if st.button("让系统分析需求" if mode == "内置案例" else "让 AI 分析需求", type="primary"):
            try:
                if demo:
                    store.select_case(case_id)
                    created = start_invited_test(store)
                else:
                    token = uuid4().hex
                    context = {"id": uuid4().hex, "token": token, "participant_id": "L"+token[:12],
                               "case_id": case_id or "custom", "error_standard": ""}
                    created = create_task(problem, selected_skills, mode="case" if case_id else "live", case_id=case_id,
                                          title=title, category=category, store=store, workflow_version=2, usability_context=context)
                st.session_state["task_id"] = created["task_id"]
                queue(created, "prepare")
                move("workspace", 1)
            except ValueError as exc:
                st.error(str(exc))


def _rules(task, view):
    meanings = {r["label"]: r["meaning"] for r in model_alignment(task)["rows"] if r["kind"] == "业务规则" and r["status"] != "已移除"}
    for rule in view["rules"]:
        if rule["kind"] == "constraint":
            meaning = meanings.get(rule["label"], rule["description"])
        else:
            meaning = rule["description"]
        st.markdown("**"+rule["label"]+"**　"+meaning)


def _modify(store, task, queue):
    if not st.session_state.get("of_modify"):
        return
    with st.container(border=True, key="of-modify-card"):
        st.subheader("需要修改什么业务规则？")
        st.write("描述遗漏或不合理的要求。提交后将保存历史版本，重新生成模型，并清除当前版本的确认和方案。")
        if task["mode"] == "case":
            st.caption("本案例支持单个数量边界，例如“产品 A 最多生产 100 件”。其他类型修改请在实时建模中创建任务。")
        method = st.radio("补充方式", ["用一句话补充", "选择产品和数量"], horizontal=True,
                          key=f"of-method-{task['task_id']}-{task['model_version']}") if task["mode"] == "case" else "用一句话补充"
        if method == "用一句话补充":
            note = st.text_area("补充或修改需求", key=f"of_revision_{task['task_id']}_{task['model_version']}", max_chars=2000,
                                placeholder="请用自己的话描述需要调整的业务要求。")
        else:
            variables = {v["name"]: v for v in task["model"]["variables"]}
            selected = st.selectbox("要限制的决策项", list(variables), format_func=lambda n: variables[n].get("label", n))
            operator = st.selectbox("数量要求", ["最多", "至少", "恰好"])
            quantity = st.number_input("数量", min_value=0.0, value=100.0, step=1.0)
            note = selected+" "+{"最多": "<=", "至少": ">=", "恰好": "=="}[operator]+f" {quantity:g} "+variables[selected].get("unit", "")
        if task["mode"] == "case" and note.strip():
            try:
                parsed = parse_case_feedback(task["case_id"], note)
                st.info("待提交的新规则："+parsed["label"]+{"<=": "最多", ">=": "至少", "==": "恰好"}[parsed["relation"]]+f" {fmt(parsed['rhs'])} {parsed['unit']}")
            except ValueError:
                st.caption("暂未识别这条规则，可以调整说法或选择产品和数量。")
        if st.button("提交修改并重新建模", type="primary"):
            try:
                revised = revise_task(task["task_id"], note, expected_version=task["model_version"], store=store, defer=True)
                queue(revised, "prepare")
                move("workspace", 1)
            except ValueError as exc:
                st.error(str(exc))
        if st.button("取消修改"):
            st.session_state.pop("of_modify", None)
            st.rerun()


def _change_notice(task):
    if task.get("revision_note"):
        st.info("本次变更："+task["revision_note"])
        if task["status"] == "awaiting_confirmation":
            st.caption("模型已更新。旧版本仅保存在历史中；请重新确认业务规则和模型，再生成当前方案。")


def _business(store, task, queue):
    _title("请检查系统是否正确理解了你的业务需求。", "重点看：目标是否正确、业务限制是否完整。正确时可以直接确认，无需填写文字反馈。")
    view = model_review_data(task["model"])
    _change_notice(task)
    with st.container(border=True, key="of-business-card"):
        st.subheader("系统理解的业务目标")
        st.write(view["goal"])
        st.subheader("需要遵守的业务规则")
        _rules(task, view)
        if view["assumptions"]:
            st.warning("需要你核对的假设："+"；".join(view["assumptions"]))
        for item in view["missing_inputs"]:
            st.error("缺失信息："+item)
        with st.expander("对照你提交的业务原文"):
            st.write(task["effective_text"])
        if task["status"] == "awaiting_confirmation" and not st.session_state.get("of_modify"):
            if st.button("确认无误，继续", type="primary"):
                try:
                    confirm_business(task["task_id"], expected_version=task["model_version"], store=store)
                    move("workspace", 2)
                except ValueError as exc:
                    st.error(str(exc))
        elif business_confirmed(task) and not st.session_state.get("of_modify"):
            st.success(f"当前 v{task['model_version']} 业务规则已确认。")
            st.button("继续检查模型", type="primary", on_click=navigate, args=("workspace", 2))
    _modify_button(task)
    _modify(store, task, queue)


def _modify_button(task):
    if task["status"] not in ACTIVE_STATUSES and not st.session_state.get("of_modify"):
        if st.button("需要修改", key="of-modify"):
            st.session_state["of_modify"] = True
            st.rerun()


def _model(store, task, queue, legacy):
    _title("检查这些规则能否代表你的业务。", "先看系统要决定什么、怎样计算目标，以及采用了哪些限制和假设。数学表达可按需展开。")
    record_view(store, task["task_id"], "model_review_opened")
    view = model_review_data(task["model"])
    _change_notice(task)
    with st.container(border=True, key="of-model-card"):
        st.subheader("系统需要决定什么")
        for var in view["decisions"]:
            st.write(f"{var['label']}（{var['unit']}）：{var['domain']}；最小 {var['lower']}，最大 {var['upper']}。")
        st.subheader("目标与建模规则")
        st.write(view["goal"])
        for rule in view["rules"]:
            matched = next((r for r in model_alignment(task)["rows"] if r["label"] == rule["label"] and r["status"] != "已移除"), None)
            st.write("• "+rule["label"]+"："+(matched["meaning"] if matched else rule["description"]))
        for item in view["assumptions"]:
            st.warning("建模假设："+item)
        with st.expander("展开原文与模型对照、变更说明"):
            alignment_panel(task)
        with st.expander("展开变量、目标函数、约束与 JSON"):
            legacy["show_model"](task["model"])
            st.text(task.get("fef_text") or "内置案例采用已标注的结构化模型，不调用实时建模服务。")
        if task["status"] == "awaiting_confirmation" and not st.session_state.get("of_modify"):
            if st.button("确认模型并计算方案", type="primary"):
                try:
                    claimed = confirm_task(task["task_id"], expected_version=task["model_version"], store=store, defer=True)
                    queue(claimed, "solve")
                    move("workspace", 3)
                except ValueError as exc:
                    st.error(str(exc))
        elif task["status"] == "completed" and not st.session_state.get("of_modify"):
            st.button("查看当前方案", type="primary", on_click=navigate, args=("workspace", 3))
        st.caption("确认表示你已复核业务含义，不构成数学正确性证明。")
    _modify_button(task)
    _modify(store, task, queue)


def _result(store, task, queue, legacy):
    _title("本次决策方案", "先看具体安排与业务收益，再按需核对计算和验证依据。")
    summary = decision_summary(task)
    if task.get("solver"):
        record_view(store, task["task_id"], "result_viewed")
    if summary["eligible"]:
        decision_panel(task, key="workspace-v2", resource_summary=True)
        st.success("求解器报告最优 · 独立数值检查通过 · 当前模型已人工确认")
        st.caption("业务语义正确性：未独立验证。建议执行前核实输入数据、建模假设与实际资源。")
    else:
        st.error((task.get("failure") or {}).get("message") or "当前尚无通过验证的方案。")
        st.write(summary["next_step"])
    if not st.session_state.get("of_modify"):
        if st.button("完成体验，填写反馈", type="primary"):
            study = study_for_task(store, task["task_id"])
            if study and summary["eligible"]:
                finish_test(store, study["id"])
            move("feedback")
    _modify_button(task)
    _modify(store, task, queue)
    with st.expander("查看决策数量图与明细"):
        solution = task.get("solver", {}).get("solution", {})
        rows = [{"决策项": v.get("label", v["name"]), "变量": v["name"], "建议数量": solution.get(v["name"]), "单位": v.get("unit", "")} for v in task["model"]["variables"]]
        if solution:
            st.html(quantity_chart_html(rows, recommended=summary["eligible"]))
            st.dataframe(rows, hide_index=True, width="stretch")
        else:
            st.info("当前没有可展示的完整决策数量。")
    with st.expander("查看求解状态、详细数值检查与代码"):
        solver = task.get("solver") or {}
        st.write("求解器状态："+solver.get("status", "未求解"))
        st.write(f"进程耗时：{solver.get('runtime_seconds', 0):.2f} 秒")
        st.write("数值可行性："+task["validation"]["numerical_feasibility"])
        st.write("模型复核："+task["human_review"]["status"]+"；业务语义：未独立验证。")
        checks = task["validation"].get("checks", [])
        if checks:
            st.dataframe(checks, hide_index=True, width="stretch")
        st.json(solver.get("solution", {}))
        if task.get("code_artifact"):
            st.json(task["code_artifact"])
            artifact = Path(task["code_artifact"].get("path", "")).resolve()
            expected = (store.path.parent / "runs" / task["task_id"] / f"v{task['model_version']}").resolve()
            if artifact.is_relative_to(expected) and artifact.is_file():
                st.code(artifact.read_text(encoding="utf-8"), language="python")
        st.caption("代码为审阅产物，实际计算由已确认结构化模型的受控解释器执行。")
    with st.expander("查看历史版本、前后对比与导出"):
        legacy["show_comparison"](task)
        st.download_button("下载决策报告", report_markdown(task), file_name=f"optiflow-v{task['model_version']}.md")
        st.download_button("下载结构化任务", json.dumps(task, ensure_ascii=False, indent=2), file_name="optiflow-task.json")


def _busy(store, task):
    status = task["status"]
    text = "正在计算并校验方案…" if status in {"solving", "executing"} else "正在分析需求并整理模型…"
    st.subheader(text)
    st.info("后台处理已开始。你可以切换页面，返回后继续；不需要重复提交。")
    if task.get("versions"):
        st.warning("需求已修改：历史结果不适用于当前版本，新的方案尚未生成。")

    @st.fragment(run_every="2s")
    def progress():
        latest = store.get(task["task_id"])
        if latest["status"] != status:
            st.rerun()
        st.progress(sum(s["status"] == "completed" for s in latest["stages"]) / 6)
        active = next((s for s in latest["stages"] if s["status"] == "running"), None)
        st.write(active["name"] if active else "等待后台工作进程更新状态")
        with st.expander("查看真实阶段状态与耗时"):
            st.dataframe(latest["stages"], hide_index=True, width="stretch")
    progress()


def _workspace(store, task, participant, queue, legacy):
    selected = st.session_state.get("of_step", current_step(task))
    st.html(f'<style>.st-key-of-stepnav [data-testid="stColumn"]:nth-child({selected+1}) button'
            '{background:#f0ecfa;color:#6554c0;border-color:#ded6f5;}</style>')
    with st.container(key="of-stepnav"):
        for index, (col, label) in enumerate(zip(st.columns(4), STEPS)):
            col.button(f"{'●' if selected == index else str(index+1)} {label}", key=f"of-step-{index}",
                       width="stretch", on_click=navigate, args=("workspace", index))
    if task:
        st.caption(f"{task['title']} · v{task['model_version']} · "+("内置案例 / 本地真实求解" if task["mode"] == "case" else "AI 实时建模"))
    if selected == 0:
        _input(store, task, participant, queue)
        return
    if task and task["status"] in ACTIVE_STATUSES:
        _busy(store, task)
        return
    if task and task.get("failure") and not task.get("model"):
        _title("这次建模没有完成。", "失败已记录，你可以补充需求后重试。")
        st.error(task["failure"]["message"])
        _modify_button(task)
        _modify(store, task, queue)
        return
    reason = step_blocker(task, selected)
    if reason:
        _title("还需要完成前面的确认。", reason)
        st.button("返回当前步骤", type="primary", on_click=navigate, args=("workspace", current_step(task)))
        return
    if selected == 1:
        _business(store, task, queue)
    elif selected == 2:
        _model(store, task, queue, legacy)
    else:
        _result(store, task, queue, legacy)
    if task:
        with st.expander("任务进度与阶段记录"):
            st.dataframe(task["stages"], hide_index=True, width="stretch")
            st.dataframe(store.events(task["task_id"]), hide_index=True, width="stretch")
            with st.expander("模型服务与技能明细"):
                st.json({"usage": task.get("usage", {}), "activated_skills": task.get("activated_skills", []),
                         "selected_references": task.get("selected_references", [])})


def _feedback(store, task):
    _title("你的体验如何？", "这里评价产品是否易用。反馈不会修改业务模型，也不影响已经得到的方案。")
    if not task or not task.get("usability_test_id"):
        st.info("请先开始一次产品体验，再提交反馈。")
        st.button("返回工作台", type="primary", on_click=navigate, args=("workspace", current_step(task)))
        return
    study = study_for_task(store, task["task_id"])
    if st.session_state.get("of_feedback_saved") == task["task_id"]:
        st.success("感谢你的反馈。已保存到后台，组织者可以统一查看和导出。")
        st.button("返回工作台", type="primary", on_click=navigate, args=("workspace", current_step(task)))
        if st.button("修改已提交的反馈"):
            st.session_state.pop("of_feedback_saved", None)
            st.rerun()
        return
    existing = json.loads(study["questionnaire"]) if study and study["questionnaire"] else {}
    if existing:
        st.caption("你已提交过反馈，再次提交会更新当前回答，历史提交仍保留在事件记录中。")
    with st.container(border=True, key="of-feedback-card"):
        st.subheader("可选的体验反馈")
        with st.form("of-experience-"+task["task_id"], border=False):
            ease = st.radio("1. 你觉得产品容易上手吗？（1 很困难，5 很容易）", range(1, 6), horizontal=True,
                            index=existing.get("ease", 0)-1 if existing.get("ease") else None, help="1 很困难，5 很容易")
            clarity = st.radio("2. 是否清楚下一步应该做什么？（1 很不清楚，5 很清楚）", range(1, 6), horizontal=True,
                               index=existing.get("clarity", 0)-1 if existing.get("clarity") else None, help="1 很不清楚，5 很清楚")
            confusing = st.selectbox("3. 哪个环节最困惑？", UX_STAGES, index=UX_STAGES.index(existing["confusing_stage"]) if existing.get("confusing_stage") in UX_STAGES else None, placeholder="请选择一个环节")
            had_problem = st.radio("4. 是否遇到操作不符合预期的情况？", ["没有", "有"], index=(1 if existing["had_problem"] else 0) if "had_problem" in existing else None, horizontal=True)
            problem = st.text_area("问题说明（选“有”时填写）", value=existing.get("problem", ""), max_chars=2000)
            improvement = st.text_area("5. 你最希望改善什么？（选填）", value=existing.get("improvement", ""), max_chars=2000)
            if st.form_submit_button("提交体验反馈", type="primary"):
                try:
                    if had_problem is None:
                        raise ValueError("请选择是否遇到问题。")
                    submit_experience(store, study["id"], ease, clarity, confusing, had_problem == "有", problem, improvement)
                    st.session_state["of_feedback_saved"] = task["task_id"]
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
    st.button("返回工作台，暂不填写", on_click=navigate, args=("workspace", current_step(task)))


def render(store, legacy):
    participant = bool(getattr(store, "participant_hash", None))
    demo = bool(getattr(store, "public_demo", False))
    if participant:
        st.session_state["of_guide_case"] = store.invite()["case_id"]
    task = _task(store)
    if "next_page" in st.session_state:
        page = st.session_state.pop("next_page")
        navigate("workspace", current_step(task))
        if page in {"任务记录与 Badcase", "建模技能库", "服务与能力"}:
            navigate({"任务记录与 Badcase": "records", "建模技能库": "skills", "服务与能力": "capabilities"}[page])
    if "of_view" not in st.session_state:
        st.session_state["of_view"] = "admin" if hosted_mode() and not participant else "guide"
    view = st.session_state["of_view"]
    with st.sidebar:
        st.html('<div class="of-brand">OptiFlow</div>')
        st.caption("智能优化决策工作台")
        st.divider()
        for label, target in [("产品导引", "guide"), ("决策工作台", "workspace"), ("体验反馈", "feedback")]:
            st.button(label, on_click=navigate, args=(target,), width="stretch", key="of-nav-"+target)
        if participant:
            if demo:
                st.caption("公开 Demo · 独立工作区")
                st.caption("内置模型，真实计算。每位访客独立体验；正式用户测试请使用专属邀请。")
                st.button("重新开始演示", on_click=new_demo, width="stretch")
            else:
                st.caption("匿名编号："+store.invite()["participant_id"])
                st.caption("操作与反馈统一保存。请保留专属链接，以便稍后继续。")
        else:
            with st.expander("历史任务与专业工具"):
                for label, target in [("任务记录与 Badcase", "records"), ("建模技能库", "skills"), ("服务与能力", "capabilities"), ("测试管理后台", "admin")]:
                    st.button(label, on_click=navigate, args=(target,), width="stretch")
        if task:
            st.divider()
            st.caption(f"当前任务 · v{task['model_version']}")
            st.write(task["title"])
    if participant and view not in {"guide", "workspace", "feedback"}:
        view = "guide"
    if view == "guide":
        _guide(task, participant)
    elif view == "workspace":
        _workspace(store, task, participant, legacy["queue"], legacy)
        st.caption("界面操作问题或改进建议，请记录到体验反馈；补充业务规则请使用“需要修改”。")
        st.button("记录界面体验问题", type="tertiary", on_click=navigate, args=("feedback",))
    elif view == "feedback":
        _feedback(store, task)
    else:
        legacy[view]()
