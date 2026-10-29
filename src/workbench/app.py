"""OptiFlow's local business decision platform. Launch via run_experiment.py."""
import html
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st

from src.workbench.cases import CASES,parse_case_feedback
from src.workbench.review_ui import alignment_panel,decision_panel
from src.workbench.jobs import launch
from src.workbench.model import ModelError, expression, validate_model
from src.workbench.explanations import model_review_data, decision_summary, compare_versions, fmt, finite
from src.workbench.charts import quantity_chart_html
from src.workbench.usability import record_view
from src.workbench.study_ui import test_entry, test_summary, study_controls
from src.workbench.hosting import hosted_mode
from src.workbench.hosting_ui import access_gate, participant_entry, admin_page
from src.workbench.manual_study import manual_session, record_comparison
from src.workbench.manual_ui import (GUIDE_PAGE, SURVEY_PAGE, COMPARE_PAGE, participant_overview,
    participant_new_task, manual_banner, step_record, guide_page, questionnaire_page)
from src.workbench.service import (ACTIVE_STATUSES, create_task, confirm_task, revise_task, report_markdown)
from src.workbench.store import TaskStore, DEFAULT_DB


st.set_page_config(page_title="OptiFlow · 智能优化决策工作台", page_icon=":material/hub:", layout="wide")
from src.workbench.public_demo import public_demo_mode, demo_database
store = TaskStore(demo_database() if public_demo_mode() else os.environ.get("OPTIFLOW_DB", DEFAULT_DB))
PAGES = ["新建优化任务", "Agent 工作流", "模型查看与确认", "求解结果与验证", "任务记录与 Badcase"]
OVERVIEW = "工作台总览"
SKILL_PAGE = "建模技能库"
CAPABILITY_PAGE = "服务与能力"
TEST_PAGE = "可用性测试"
ADMIN_PAGE = "测试管理后台"
STATUS = {"pending": "排队中", "modeling": "正在建模", "revising": "正在重建", "awaiting_confirmation": "待确认模型",
          "solving": "准备求解", "executing": "正在求解", "completed": "方案已生成", "failed": "任务失败",
          "no_solution": "未获得可行方案", "needs_attention": "结果待复核"}


def local_time(value):
    return datetime.fromisoformat(value).astimezone(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")

st.html("""<style>
.stApp {background:#f6f7fb;}
.block-container {max-width:1380px;padding-top:5rem;padding-bottom:3rem;}
h1 {font-size:2.3rem!important;letter-spacing:-.06em; font-weight:750!important;}
h2 {font-size:1.4rem!important;letter-spacing:-.035em;}
h3 {font-size:1.08rem!important;}
[data-testid="stSidebar"] {background:#111d35;}
[data-testid="stSidebar"] * {color:#dbe3f6;}
[data-testid="stSidebar"] [data-testid="stRadio"] label {padding:.35rem 0;}
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] * {color:#94a4c4!important;}
[data-testid="stSidebar"] [role="radiogroup"] label {border-radius:8px;padding:9px 12px;margin:3px 0;}
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {background:#315df5;}
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) * {color:white!important;}
[data-testid="stSidebar"] [data-testid="stMetricValue"] {font-size:1.65rem;}
[data-testid="stVerticalBlockBorderWrapper"] {border-radius:14px;}
[data-testid="stMetric"] {box-sizing:border-box;background:white;border:1px solid #e5e9f1;border-radius:12px;padding:18px;height:auto!important;min-height:112px;overflow:visible;}
[data-testid="stMetricLabel"] {color:#68758c;}
[data-testid="stMetricValue"] {font-size:1.7rem;letter-spacing:-.04em;}
.eyebrow {color:#315df5;font-size:11px;font-weight:750;letter-spacing:.16em;margin-bottom:12px;}
.sub {color:#738099;font-size:14px;line-height:1.9;margin-bottom:25px;}
.brand {display:flex;gap:12px;align-items:center;margin:12px 0 8px;}
.brand-mark {background:#315df5;color:white;border-radius:10px;width:38px;height:38px;display:grid;place-items:center;font-size:23px;font-weight:800;}
.brand-name {font-size:23px;font-weight:750;letter-spacing:-1px;color:white!important;}
.pill {display:inline-block;background:#edf1ff;color:#315df5;border:1px solid #dfe6ff;border-radius:6px;padding:5px 10px;font-size:12px;margin:0 5px 14px 0;}
.stage {display:flex;align-items:center;gap:16px;padding:18px 0;border-bottom:1px solid #edf0f5;}
.stage-num {border:1px solid #dbe3f0;border-radius:10px;width:38px;height:38px;display:grid;place-items:center;color:#6d7c96;background:white;flex-shrink:0;}
.stage-num.completed {background:#e9f8f2;color:#198c69;border-color:#cfeddf;}
.stage-num.running {background:#edf1ff;color:#315df5;border-color:#c8d4ff;}
.stage-num.failed {background:#fff0ee;color:#c55245;}
.stage-main {flex:1;}.stage-title {font-size:15px;font-weight:650;}.stage-note {color:#77849b;font-size:12px;margin-top:5px;}
.stage-state {color:#77849b;font-size:12px;text-align:right;}
.formula {background:#f4f6fb;padding:18px;border-radius:9px;font-size:17px;line-height:1.8;font-family:Consolas,monospace;overflow-wrap:anywhere;}
.source {color:#6e7e96;font-size:12px;line-height:1.8;margin-top:10px;}
.case-no {color:#315df5;font-size:11px;letter-spacing:.12em;font-weight:700;}
.footer {color:#8c97aa;font-size:11px;letter-spacing:.06em;margin-top:30px;}
.hero {padding:26px 30px;border:1px solid #dbe4ff;border-radius:14px;background:linear-gradient(120deg,#edf2ff,#fff);margin-bottom:22px;}
.hero-title {font-size:24px;font-weight:750;letter-spacing:-.04em;margin:8px 0 14px;}
.hero-note {color:#64748b;font-size:14px;line-height:1.9;max-width:850px;}
.flow-strip {display:flex;align-items:center;gap:8px;flex-wrap:wrap;padding:15px 0;}
.flow-chip {background:white;border:1px solid #d9e2f5;padding:9px 13px;border-radius:8px;font-size:12px;color:#4c607f;}
.flow-chip.review {background:#e8f7f0;border-color:#c1e8d4;color:#167651;font-weight:700;}
button {border-radius:8px!important;}
#manual-step-record, #manual-step-guide, .quantity-chart, .st-key-manual-guide, .st-key-manual-record, .st-key-model-alignment, .st-key-decision-brief-result, .st-key-decision-brief-compare {scroll-margin-top:90px;}
.st-key-manual-guide, .st-key-manual-record {box-sizing:border-box;min-width:0;}
.study-steps {display:flex;gap:7px;flex-wrap:wrap;margin:0 0 14px;}
.study-step {padding:7px 10px;border:1px solid #dde3ef;border-radius:8px;background:#fff;color:#7b8598;font-size:12px;line-height:1.5;}
.study-step.current {color:#3046ba;border-color:#c9d2ff;background:#edf1ff;font-weight:650;}
.study-step.done {color:#247d68;border-color:#cfe9df;background:#eef8f3;}
.quantity-chart {box-sizing:border-box;background:#fff;border:1px solid #e1e6f0;border-radius:14px;padding:24px;margin:14px 0 22px;overflow:visible;}
.quantity-title {font-size:18px;font-weight:700;color:#1d2c44;}
.quantity-caption {color:#748198;font-size:13px;line-height:1.7;margin:7px 0 25px;}
.quantity-group+.quantity-group {border-top:1px solid #edf0f5;margin-top:22px;padding-top:18px;}
.quantity-unit {font-size:12px;color:#748198;margin-bottom:16px;}
.quantity-row {margin-bottom:22px;}
.quantity-row-heading {display:flex;align-items:baseline;justify-content:space-between;gap:16px;flex-wrap:wrap;margin-bottom:10px;color:#37445c;}
.quantity-row-heading>span {display:flex;gap:9px;align-items:center;font-size:14px;overflow-wrap:anywhere;}
.quantity-row-heading i {width:9px;height:9px;border-radius:3px;display:inline-block;flex-shrink:0;}
.quantity-row-heading strong {font-size:24px;font-weight:700;font-variant-numeric:tabular-nums;color:#22304a;white-space:nowrap;}
.quantity-row-heading small {font-size:13px;font-weight:400;color:#77849a;}
.quantity-track {height:22px;border-radius:6px;background:repeating-linear-gradient(90deg,#f2f4f9 0%,#f2f4f9 calc(25% - 1px),#e6eaf2 calc(25% - 1px),#e6eaf2 25%);position:relative;}
.quantity-zero {position:absolute;top:0;height:100%;width:1px;background:#d5ddea;}
.quantity-fill {position:absolute;top:0;height:100%;border-radius:6px;min-width:0;}
.quantity-axis {display:flex;justify-content:space-between;font-size:11px;color:#8792a4;font-variant-numeric:tabular-nums;margin-top:-10px;}
@media(max-width:640px){.block-container{padding-top:5rem;padding-left:1rem;padding-right:1rem;}h1{font-size:1.9rem!important;}.quantity-chart{padding:18px;}.quantity-row-heading strong{font-size:22px;}}
</style>""")

from src.workbench.theme import apply_theme
apply_theme()
store = access_gate(store)
participant_mode = bool(getattr(store, "participant_hash", None))
manual_mode = participant_mode and bool(manual_session(store))


def go(page):
    # Apply before the sidebar widget is instantiated on the next full run.
    st.session_state["next_page"] = page


def header(index, title, subtitle):
    st.html(f'<div class="eyebrow">OPTIFLOW / 智能优化决策工作台 / {index:02d}</div>')
    st.title(title)
    st.html(f'<div class="sub">{html.escape(subtitle)}</div>')


def current_task():
    identifier = st.session_state.get("task_id")
    try:
        return store.get(identifier) if identifier else None
    except (ValueError, PermissionError):
        st.session_state.pop("task_id", None)
        return None


def require_task():
    task = current_task()
    if not task:
        st.info("先创建一个优化任务，或从任务记录中打开已有任务。", icon=":material/info:")
        st.button("开始我的测试" if participant_mode else "创建第一个任务", on_click=go, args=(TEST_PAGE if participant_mode else PAGES[0],), type="primary")
        return None
    mode = "内置案例 · 本地真实求解" if task["mode"] == "case" else "AI · 实时建模"
    st.html(f'<span class="pill">{mode}</span><span class="pill">{html.escape(STATUS.get(task["status"], task["status"]))}</span>'
            f'<span class="pill">模型 v{task["model_version"]}</span>')
    st.caption(f'{task["title"]}  /  {task["task_id"][:12]}')
    return task


def queue(task, action):
    try:
        launch(task["task_id"], action, store)
    except OSError:
        # A launch failure must never leave a task spinning indefinitely.
        task["status"] = "failed"
        task["failure"] = {"stage": "setup", "kind": "worker_launch_failed", "message": "本地工作进程启动失败，请检查 Python 环境后新建任务。"}
        store.save(task, "task_failed", task["failure"])


def new_task():
    if manual_mode:
        participant_new_task(store, go, queue)
        return
    header(1, "把业务问题，变成可执行的决策。", "描述你的目标与资源限制。OptiFlow 会先建立可检查的模型，确认后再生成决策方案。")
    left, right = st.columns([2.1, 1], gap="large")
    with left:
        with st.container(border=True):
            st.subheader("定义一个优化任务", anchor=False)
            mode_label = st.radio("运行方式", ["内置案例 · 本地真实求解", "AI · 实时建模"], horizontal=True, key="input_mode")
            mode = "case" if mode_label.startswith("内置") else "live"
            selected = st.selectbox("预置业务案例", list(CASES), format_func=lambda k: CASES[k]["title"], key="case_id")
            case = CASES[selected]
            if st.button("加载到需求输入框", icon=":material/download:"):
                st.session_state["problem_input"] = case["text"]
                st.session_state["task_title_input"] = case["title"]
                st.session_state["task_category"] = case["category"]
            if "problem_input" not in st.session_state:
                st.session_state["problem_input"] = case["text"]
                st.session_state["task_title_input"] = case["title"]
            title = st.text_input("任务名称", key="task_title_input", max_chars=80)
            category = st.selectbox("任务类别", ["生产计划", "资源分配", "人员排班", "物流运输", "其他"], key="task_category")
            text = st.text_area("业务需求", key="problem_input", height=205, max_chars=16000,
                                placeholder="希望优化什么？可用资源有多少？有哪些必须满足的条件？")
            st.caption("建议包含：决策对象、目标、具体数值、资源限制、数量边界及单位。")
            selected_skills = None
            if mode == "live":
                st.info("将调用 src/config.py 配置的模型服务。模型完成后等待你确认；当前支持 LP / MILP。")
                with st.expander("可选：指定建模 Skill"):
                    from src.skill_loader import load_skills
                    skills = load_skills(Path(__file__).resolve().parents[2] / "skill_library")
                    automatic = st.checkbox("自动检索相关 Skill", value=True)
                    if not automatic:
                        selected_skills = st.multiselect("候选 Skill（空列表表示不注入知识）", [s.name for s in skills])
            else:
                st.caption("案例使用已标注模型，确认后调用本机求解器。自定义输入请切换实时建模；修改案例后请重新加载。")
            if st.button("生成可确认的模型", type="primary", icon=":material/arrow_forward:", width="stretch"):
                try:
                    task = create_task(text, selected_skills, mode=mode, case_id=selected, title=title, category=category, store=store)
                    st.session_state["task_id"] = task["task_id"]
                    queue(task, "prepare")
                    go(PAGES[1])
                    st.rerun()
                except (ModelError, ValueError) as exc:
                    st.error(str(exc))
    with right:
        st.html('<div class="eyebrow">YOUR DECISION, IN CONTROL</div>')
        st.subheader("每一步，都有依据", anchor=False)
        st.markdown("**01　先看懂模型**\n\n变量、目标与约束，对照业务原文检查。\n\n**02　再确认求解**\n\n发现遗漏就补充需求，生成新版本。\n\n**03　分别检查结果**\n\n查看求解状态、数值可行性与人工复核记录。")
        st.divider()
        st.caption("适用场景")
        for case in CASES.values():
            st.markdown(f"**{case['title']}**")
            st.caption(case["description"])
        st.caption("MVP 范围：线性 / 混合整数线性问题。本地单用户工作台。")
    st.html('<div class="footer">FROM BUSINESS REQUIREMENTS TO REVIEWABLE DECISIONS</div>')


@st.fragment(run_every="2s")
def workflow_panel():
    task = current_task()
    if not task:
        return
    if task["status"] != st.session_state.get("workflow_rendered_status"):
        st.rerun()
    st.progress(sum(s["status"] == "completed" for s in task["stages"]) / 6)
    labels = {"completed": "已完成", "pending": "待开始", "running": "进行中", "failed": "失败", "blocked": "已阻塞"}
    for index, stage in enumerate(task["stages"], 1):
        detail = stage.get("detail", "模型确认后继续" if index > 3 else "等待上一步完成")
        elapsed = f" · {stage['elapsed_seconds']:.2f}s" if "elapsed_seconds" in stage else ""
        st.html(f'<div class="stage"><div class="stage-num {stage["status"]}">{"✓" if stage["status"] == "completed" else f"{index:02d}"}</div>'
                f'<div class="stage-main"><div class="stage-title">{stage["name"]}</div><div class="stage-note">{html.escape(detail)}</div></div>'
                f'<div class="stage-state">{labels[stage["status"]]}{elapsed}</div></div>')
    if task["status"] == "awaiting_confirmation":
        st.info("模型已生成。请先检查变量、目标、约束与假设，确认后继续求解。", icon=":material/pan_tool:")
        if st.button("检查并确认模型", type="primary", icon=":material/arrow_forward:"):
            go(PAGES[2])
            st.rerun()
    elif task["status"] in {"completed", "no_solution", "needs_attention"}:
        if st.button("查看求解结果", type="primary"):
            go(PAGES[3])
            st.rerun()
    elif task["failure"]:
        st.error(task["failure"]["message"])
        if task.get("model"):
            if st.button("返回模型补充需求"):
                go(PAGES[2])
                st.rerun()
    elif task["status"] in ACTIVE_STATUSES:
        st.caption("后台正在处理，可切换页面；进度每 2 秒从本地任务库刷新。")


def workflow():
    header(2, "从需求到方案，进度清晰可见。", "查看各阶段真实状态。数学建模完成后，流程会暂停等待你的确认。")
    task = require_task()
    if not task:
        return
    st.session_state["workflow_rendered_status"] = task["status"]
    left, right = st.columns([2, 1], gap="large")
    with left:
        with st.container(border=True):
            workflow_panel()
    with right:
        with st.container(border=True):
            st.subheader("任务需求", anchor=False)
            st.write(task["effective_text"])
        if task.get("usage"):
            with st.container(border=True):
                st.subheader("模型服务用量", anchor=False)
                usage = list(task["usage"].values())
                st.metric("调用次数", sum(u["calls"] for u in usage))
                st.metric("记录的 token 用量", sum(u["total_tokens"] for u in usage))
                st.caption(f'其中 {sum(u["estimated_calls"] for u in usage)} 次调用的用量含估算。未配置计价，不展示虚构费用。')
        if not participant_mode:
            with st.expander("阶段事件与耗时"):
                st.dataframe(store.events(task["task_id"]), hide_index=True, width="stretch")


def source(item):
    original = item.get("source") if isinstance(item.get("source"), str) else ""
    st.html('<div class="source">' + ("原文依据 · “" + html.escape(original) + "”" if original else
            "待确认假设 · " + html.escape(str(item.get("assumption", "")))) + '</div>')


def show_model(model):
    view = model_review_data(model)
    st.subheader("01　系统对业务目标的理解", anchor=False)
    st.write(view["goal"])
    with st.expander("目标的原文依据与数学表达"):
        source(view["objective"])
        st.code(view["objective_formula"], language=None)
    st.subheader("02　需要决定什么？", anchor=False)
    if not view["decisions"]:
        st.warning("尚无完整决策对象，请补充需求或重新建模。")
    for v in view["decisions"]:
        with st.container(border=True):
            st.markdown(f"**{v['label']}**")
            st.write(f"单位：{v['unit']} · 数值类型：{v['domain']}")
            st.caption(f"最小值：{v['lower']} · 最大值：{v['upper']}")
            with st.expander("来源与技术定义"):
                source(v)
                st.code(f"{v['name']} · {v['technical_domain']}", language=None)
    st.subheader("03　识别到的业务规则", anchor=False)
    if not view["rules"]:
        st.warning("尚无完整业务规则，请核实是否遗漏条件。")
    for rule in view["rules"]:
        with st.container(border=True):
            st.markdown(f"**{rule['label']}**")
            st.write(rule["description"])
            with st.expander("查看原文依据与数学表达"):
                source(rule)
                st.code(rule["formula"], language=None)
    st.subheader("04　假设与缺失信息", anchor=False)
    if view["assumptions"]:
        for item in view["assumptions"]:
            st.warning(item, icon=":material/help:")
    else:
        st.caption("未记录额外建模假设。仍需检查是否符合业务原意。")
    for item in view["missing_inputs"]:
        st.error(f"缺失输入：{item}")
    st.caption("原文引用表示可追溯，仍需你核对规则、数值与实际业务是否一致。")
    with st.expander("查看结构化模型 JSON"):
        st.json(model)


def model_review():
    task = require_task()
    if not task:
        return
    header(3, "新要求已进入模型，看看这次改了什么。" if task["model_version"]>1 else "业务需求如何变成可核对的规则？",
           "左侧对照业务原文与系统规则，右侧补充需求或确认。原始需求、模型规则和计算出的决策是三个不同步骤。")
    if not task["model"]:
        st.info("模型尚未就绪，请在工作流查看进度或失败原因。")
        st.button("查看工作流", on_click=go, args=(PAGES[1],))
        return
    record_view(store, task["task_id"], "model_review_opened")
    view = model_review_data(task["model"])
    shape_valid = True
    try:
        validate_model(task["model"], task["effective_text"])
    except (ModelError, TypeError, KeyError):
        shape_valid = False
        st.error("当前模型结构不完整或依据无法匹配，已禁止确认。请补充需求后重新建模。")
    st.write(f"优化目标：{view['objective_label']}")
    for col, title, value in zip(st.columns(4), ["需决定的数量", "模型显式约束", "待确认假设", "缺失输入"],
                               [view["variable_count"], view["constraint_count"], len(view["assumptions"]), len(view["missing_inputs"])]):
        col.metric(title, value)
    left, right = st.columns([2, 1], gap="large")
    with left:
        st.caption("模型来源：实时大模型建模。请核对模型是否符合原意。" if task["mode"]=="live" else "模型来源：预置业务案例。本次不调用大模型，确认后真实求解；补充要求会生成新的模型版本。")
        alignment,technical=st.tabs(["业务与模型对照","完整模型与公式"])
        with alignment:
            with st.container(key="model-alignment"):
                alignment_panel(task)
        with technical:
            show_model(task["model"])
            with st.expander("查看建模说明"):
                st.text(task.get("fef_text", "内置案例采用人工标注的线性模型，不调用大模型。"))
    with right:
        with st.container(border=True):
            st.subheader("最初的业务需求", anchor=False)
            st.write(task["problem_text"])
            if task.get("feedback"):
                st.caption("后续补充的新要求（未改写原文）")
                for note in task["feedback"]:
                    st.write(note)
        with st.container(border=True):
            st.subheader("发现遗漏？补充一条业务规则", anchor=False)
            input_method="用一句话补充"
            if task["mode"] == "case":
                input_method=st.radio("补充方式",["用一句话补充","选择产品和数量"],key=f'feedback_mode_{task["task_id"]}_{task["model_version"]}')
            if input_method=="用一句话补充":
                feedback = st.text_area("补充需求", placeholder="例如：A 每天最多生产 100 件的新要求", height=125, key=f'feedback_{task["task_id"]}_{task["model_version"]}')
            else:
                variables={v["name"]:v for v in task["model"]["variables"]}
                selected=st.selectbox("要限制的决策项",list(variables),format_func=lambda n:variables[n].get("label",n))
                operator=st.selectbox("数量要求",["最多","至少","恰好"])
                quantity=st.number_input("数量",min_value=0.0,value=100.0,step=1.0)
                feedback=f"{selected} "+{"最多":"<=","至少":">=","恰好":"=="}[operator]+f" {quantity:g} "+variables[selected].get("unit","")
            if task["mode"]=="case":
                st.caption("支持一条决策数量的上限、下限或固定值。也可选择产品和数量，无需组织句子。")
                if feedback.strip():
                    try:
                        preview=parse_case_feedback(task["case_id"],feedback)
                        word={"<=":"最多",">=":"至少","==":"恰好"}[preview["relation"]]
                        st.info(f"识别到的新规则：{preview['label']}{word} {fmt(preview['rhs'])} {preview['unit']}。提交后请核对新版本。")
                    except ModelError:
                        st.caption("暂未识别。可调整说法，或使用“选择产品和数量”。")
            editable = task["status"] not in ACTIVE_STATUSES and task["status"]!="executing"
            if st.button("补充需求并重新建模", disabled=not editable, width="stretch", icon=":material/edit_note:"):
                try:
                    updated = revise_task(task["task_id"], feedback, expected_version=task["model_version"], store=store, defer=True)
                    queue(updated, "prepare")
                    go(PAGES[1])
                    st.rerun()
                except (ValueError, ModelError) as exc:
                    st.error(str(exc))
        with st.container(border=True):
            st.subheader("确认当前版本", anchor=False)
            st.markdown("核对提示：\n\n- 决策对象是否正确？\n- 优化目标是否符合需求？\n- 是否遗漏业务限制？\n- 数量边界、单位和假设是否合理？")
            confirmed = st.checkbox("已检查变量、目标、约束、边界和假设，模型符合当前业务需求。", key=f'accept_{task["task_id"]}_{task["model_version"]}')
            st.caption("人工确认记录业务复核，不代表模型已被数学证明正确。补充需求会撤销当前确认并生成新版本。")
            if st.button("确认模型并求解", type="primary", width="stretch", icon=":material/play_arrow:",
                         disabled=not shape_valid or not confirmed or task["status"] != "awaiting_confirmation" or bool(view["missing_inputs"])):
                try:
                    updated = confirm_task(task["task_id"], expected_version=task["model_version"], store=store, defer=True)
                    queue(updated, "solve")
                    go(PAGES[1])
                    st.rerun()
                except (ValueError, ModelError) as exc:
                    st.error(str(exc))
            if task["human_review"]["status"] == "confirmed":
                st.success(f'v{task["human_review"]["version"]} 已人工确认')
        study_controls(store, task)


def show_comparison(task):
    versions = [*task["versions"], task]
    rows = [{"版本": f'v{v["model_version"]}', "约束数": len((v.get("model") or {}).get("constraints", [])),
             "求解状态": (v.get("solver") or {}).get("status", "未求解"),
             "目标值": (v.get("solver") or {}).get("objective_value"),
             "决策量": json.dumps((v.get("solver") or {}).get("solution", {}), ensure_ascii=False),
             "人工复核": (v.get("human_review") or {}).get("status", "pending")} for v in versions]
    with st.expander("全部版本与求解状态"):
        st.dataframe(rows, hide_index=True, width="stretch")
    available = {v["model_version"]: v for v in versions if (v.get("solver") or {}).get("solution")
                 and finite((v.get("solver") or {}).get("objective_value"))}
    if len(available) >= 2:
        keys = sorted(available)
        a, b = st.columns(2)
        old = a.selectbox("基准版本", keys, format_func=lambda n: f"v{n}", key=f"compare_old_{task['task_id']}_{task['model_version']}")
        new = b.selectbox("对比版本", keys, index=len(keys)-1, format_func=lambda n: f"v{n}", key=f"compare_new_{task['task_id']}_{task['model_version']}")
        difference = compare_versions(available[old], available[new])
        st.write(difference["summary"])
        st.caption("对应需求变更：" + str(difference["change_note"]))
        st.dataframe([{"版本": f"v{v['model_version']}", "目标值": v["solver"]["objective_value"],
                       "求解状态": v["solver"]["status"], "数值检查": v["validation"]["numerical_feasibility"]}
                      for v in [available[old], available[new]]], hide_index=True, width="stretch")
        if difference["comparable"]:
            a, b = st.columns(2)
            a.metric("目标值变化量（对比 − 基准）", fmt(difference["delta"]))
            b.metric("相对变化（变化量 / |基准值|）", f"{difference['relative_percent']:.2f}%" if difference["relative_percent"] is not None else "不可计算：基准值为 0")
        st.dataframe([{"决策项": r["label"], "变量": r["variable"], "基准数量": r["before"], "对比数量": r["after"],
                       "变化量": r["delta"], "含义与单位一致": r["semantics_match"]} for r in difference["variables"]], hide_index=True, width="stretch")
        return old, new
    else:
        st.info("至少需要两个返回完整结果的模型版本，才能选择对比。未求解或空结果版本保留在全部版本记录中。")


def results():
    context=current_task() or {}
    production=context.get("category")=="生产计划" or context.get("mode")=="case" and context.get("case_id")=="production"
    header(4, "生产决策建议" if production else "业务决策建议", "先看具体安排、目标值与变更影响，再核对验证依据。")
    task = require_task()
    if not task:
        return
    solver = task.get("solver", {})
    if not solver:
        st.info("当前版本尚无求解结果。先确认模型，再查看求解工作流。")
        st.button("查看模型", on_click=go, args=(PAGES[2],), type="primary")
        return
    record_view(store, task["task_id"], "result_viewed")
    summary = decision_panel(task)
    obj = task["model"]["objective"]
    cols = st.columns(4)
    cols[0].metric("求解器状态", solver["status"])
    cols[1].metric(obj.get("label", "目标值"), f'{solver["objective_value"]:,.2f}' if solver.get("objective_value") is not None else "—")
    cols[2].metric("求解进程耗时", f'{solver.get("runtime_seconds", 0):.2f} s')
    cols[3].metric("数值检查", {"passed": "通过", "failed": "未通过", "not_checked": "未检查"}[task["validation"]["numerical_feasibility"]])
    st.caption(f'后端：{solver.get("backend", "unknown")} · 目标单位：{obj.get("unit", "未标注")} · 耗时包含子进程启动与求解。')
    a, b, c = st.columns(3)
    a.info(f'求解器报告：{solver["status"]}')
    b.info(f'人工复核：v{task["human_review"]["version"]} 已确认' if task["human_review"]["status"] == "confirmed" else "人工复核：未确认")
    c.info("业务语义正确性：未独立验证")
    if task["failure"]:
        st.warning(task["failure"]["message"])
    overview, residuals, compare, exports = st.tabs(["决策方案", "约束与残差", "版本对比", "导出与追溯"])
    with overview:
        if solver.get("solution"):
            st.subheader("建议决策量" if summary["eligible"] else "求解器返回值（待复核）", anchor=False)
            rows = [{"决策项": v.get("label", v["name"]), "变量": v["name"], "建议数量": solver["solution"].get(v["name"]),
                     "单位": v.get("unit", "")} for v in task["model"]["variables"]]
            st.html(quantity_chart_html(rows, recommended=summary["eligible"]))
            with st.expander("查看数量明细表"):
                st.dataframe(rows, hide_index=True, width="stretch")
        else:
            st.warning("没有可展示的决策量。若模型不可行，请检查资源约束与最低需求是否冲突；若无界，请检查数量上限。")
        st.button("补充需求 / 调整方案", on_click=go, args=(PAGES[2],), icon=":material/tune:")
    with residuals:
        st.caption("残差 = 左值 − 右值；违反量按约束方向计算，0 表示未违反。容差采用绝对与相对尺度，整数性单独检查。")
        checks = task["validation"].get("checks", [])
        if checks:
            st.dataframe([{"检查项": x["name"], "左值": x["lhs"], "关系": x["relation"], "右值": x["rhs"],
                           "残差": x["residual"], "违反量": x["violation"], "容差": x["tolerance"],
                           "通过": x["passed"]} for x in checks], hide_index=True, width="stretch")
        else:
            st.info(task["validation"].get("reason", "当前没有完整决策量，无法检查数值可行性。"))
    with compare:
        show_comparison(task)
    with exports:
        left, right = st.columns(2)
        left.download_button("下载决策报告 .md", report_markdown(task), file_name=f'optiflow_{task["task_id"][:8]}_v{task["model_version"]}.md', mime="text/markdown", width="stretch")
        right.download_button("下载结构化任务 .json", json.dumps(task, ensure_ascii=False, indent=2), file_name=f'optiflow_{task["task_id"][:8]}.json', mime="application/json", width="stretch")
        st.caption(f'已确认模型指纹：{task["human_review"].get("model_hash", "—")}')
        if task.get("code_artifact"):
            st.caption(task["code_artifact"]["note"])
    study_controls(store, task)
    if manual_mode and task.get("versions") and st.button("比较前后方案", type="primary"):
        go(COMPARE_PAGE)
        st.rerun()


def comparison_page():
    header(6, "比较两次生产计划。", "核对新增要求前后的模型、建议数量与利润，并形成你的解释。")
    task = require_task()
    if task:
        decision_panel(task,key="compare")
        selected = show_comparison(task)
        if selected == (1, task["model_version"]) and task["model_version"] > 1:
            record_comparison(store, task)
        else:
            st.caption("本次 T6 请对比基准版本 v1 和增加要求后的当前版本。")


def records():
    header(5, "把每次任务，沉淀为下一次改进。", "集中查看任务、模型版本与失败原因，记录问题处理进度。")
    metrics = store.metrics()
    columns = st.columns(4)
    for col, label, key in zip(columns, ["本地任务", "已确认次数", "需求修订次数", "数值通过任务"], ["tasks", "confirmations", "revisions", "numerically_passed"]):
        col.metric(label, metrics[key])
    st.caption("以上为本机使用记录，不代表真实用户规模或商业收益。")
    tasks_tab, bad_tab, study_tab = st.tabs(["任务记录", "Badcase 跟进", "可用性测试汇总"])
    with study_tab:
        test_summary(store)
    tasks = store.list()
    with tasks_tab:
        if not tasks:
            st.info("暂无任务。创建第一个任务后，模型版本和确认记录会保存在本机。")
        else:
            st.dataframe([{"任务": t["title"], "状态": STATUS.get(t["status"], t["status"]), "模式": "内置案例" if t["mode"] == "case" else "实时建模",
                           "用途": "可用性测试" if t.get("usability_test_id") else "普通任务",
                           "版本": t["model_version"], "类别": t["category"], "创建时间（北京时间）": local_time(t["created_at"]), "ID": t["task_id"][:12]} for t in tasks], hide_index=True, width="stretch")
            selected = st.selectbox("选择历史任务", [t["task_id"] for t in tasks], format_func=lambda k: next(f'{t["title"]} · {k[:8]}' for t in tasks if t["task_id"] == k))
            if st.button("打开任务", type="primary", icon=":material/open_in_new:"):
                st.session_state["task_id"] = selected
                go(PAGES[2])
                st.rerun()
    with bad_tab:
        bad = [t for t in tasks if t.get("failure")]
        if not bad:
            st.info("暂无失败记录。不可行、无界、服务错误与数值检查失败会归入这里。")
        else:
            st.dataframe([{"任务": t["title"], "阶段": t["failure"]["stage"], "错误分类": t["failure"]["kind"],
                           "原因": t["failure"]["message"], "处理状态": t["badcase_status"]} for t in bad], hide_index=True, width="stretch")
            selected = st.selectbox("跟进任务", [t["task_id"] for t in bad], format_func=lambda k: next(t["title"] for t in bad if t["task_id"] == k))
            item = store.get(selected)
            disposition = st.selectbox("处理状态", ["待处理", "排查中", "已处理"], index=["待处理", "排查中", "已处理"].index(item["badcase_status"]))
            note = st.text_area("处理说明", value=item.get("badcase_note", ""))
            if st.button("保存跟进"):
                item.update(badcase_status=disposition, badcase_note=note)
                store.save(item, "badcase_updated", {"status": disposition, "note": note})
                st.success("已保存。该状态仅表示跟进进度，不会改变求解与校验结果。")


def load_template(case_id):
    case = CASES[case_id]
    st.session_state.update(case_id=case_id, problem_input=case["text"], task_title_input=case["title"],
                            task_category=case["category"], input_mode="内置案例 · 本地真实求解")
    go(PAGES[0])


def overview():
    header(0, "让每一次业务决策，都有可检查的依据。", "从一句需求到可执行方案，把建模、复核、求解与改进放进同一个工作空间。")
    st.html('<div class="hero"><div class="eyebrow">BUSINESS → MODEL → DECISION</div>'
            '<div class="hero-title">先把问题说清楚，再把方案算明白。</div>'
            '<div class="hero-note">生产多少、资源怎么分、人员怎么排？描述你的目标与限制，AI 生成模型。'
            '你可以检查依据、补充条件，确认后再求解，并查看方案是否满足全部约束。</div>'
            '<div class="flow-strip"><span class="flow-chip">描述业务需求</span> → <span class="flow-chip">生成可检查模型</span> → '
            '<span class="flow-chip review">人工确认 / 补充需求</span> → <span class="flow-chip">求解与验证</span> → '
            '<span class="flow-chip">方案复盘</span></div></div>')
    a, b = st.columns([1, 3])
    a.button("新建优化任务", key="home_create", type="primary", on_click=go, args=(PAGES[0],), width="stretch", icon=":material/add:")
    b.button("查看能力与使用说明", on_click=go, args=(CAPABILITY_PAGE,), icon=":material/info:")
    metrics = store.metrics()
    columns = st.columns(4)
    for col, label, key in zip(columns, ["已创建任务", "待确认模型", "数值通过任务", "待跟进问题"],
                               ["tasks", "awaiting_confirmation", "numerically_passed", "open_badcases"]):
        col.metric(label, metrics[key])
    st.caption("以上来自本机真实任务记录。首次使用显示为 0；未预填用户量、业务收益或虚构任务。")
    st.subheader("从一个业务场景开始", anchor=False)
    for column, case in zip(st.columns(3), CASES.values()):
        with column, st.container(border=True):
            st.html(f'<div class="case-no">{case["category"]} / BUSINESS TEMPLATE</div>')
            st.subheader(case["title"], anchor=False)
            st.write(case["description"])
            st.caption("已标注业务模型 · 确认后本机真实求解")
            st.button("使用这个模板", key=f'home_{case["id"]}', on_click=load_template, args=(case["id"],), width="stretch")
    left, right = st.columns([1.7, 1], gap="large")
    with left, st.container(border=True):
        st.subheader("最近任务", anchor=False)
        tasks = store.list(5)
        if not tasks:
            st.info("还没有任务。选择一个业务模板，体验从模型确认到方案验证的完整流程。")
        for task in tasks:
            a, b = st.columns([3, 1])
            a.markdown(f'**{task["title"]}**')
            a.caption(f'{STATUS.get(task["status"], task["status"])} · v{task["model_version"]} · {local_time(task["created_at"])}')
            if b.button("打开", key=f'open_{task["task_id"]}'):
                st.session_state["task_id"] = task["task_id"]
                go(PAGES[2] if task.get("model") else PAGES[1])
                st.rerun()
    with right, st.container(border=True):
        st.subheader("平台的三个关键约定", anchor=False)
        st.markdown("**先确认，再求解**\n\n模型生成后暂停；补充需求后重新确认。\n\n**结果分别检查**\n\n求解状态、数值可行性、人工复核分别记录。\n\n**修改能够追溯**\n\n需求、模型与方案按版本保留，便于复盘。")


def skill_catalog():
    header(6, "把建模方法，沉淀为可复用能力。", "按任务识别、建模技巧与求解实现组织技能。每个条目包含使用条件和适用边界。")
    from src.skill_loader import load_skills
    from src.knowledge_delivery import norm_category
    skills = load_skills(Path(__file__).resolve().parents[2] / "skill_library")
    names = {"K1": "任务类型", "K2": "建模技巧", "K3": "求解实现"}
    left, right = st.columns([2, 1])
    query = left.text_input("搜索技能", placeholder="例如：capacity、整数、transportation")
    category = right.selectbox("能力类别", ["全部", *names.values()])
    filtered = [s for s in skills if (category == "全部" or names[norm_category(s.category)] == category)
                and (not query or query.casefold() in (s.name + s.description + s.body
                     + s.knowledge_unit.get("display_title", "") + s.knowledge_unit.get("display_description", "")).casefold())]
    st.caption(f"共 {len(skills)} 项可复用技能，当前显示 {len(filtered)} 项。目录内容是建模参考，不能替代业务条件。")
    for index in range(0, len(filtered), 3):
        for column, skill in zip(st.columns(3), filtered[index:index + 3]):
            with column, st.container(border=True):
                title = skill.knowledge_unit.get("display_title") or skill.knowledge_unit.get("title", skill.name)
                st.html(f'<span class="pill">{names[norm_category(skill.category)]}</span>')
                st.markdown(f"**{title}**")
                st.caption(skill.name)
                st.write(skill.knowledge_unit.get("display_description") or skill.use_when)
                with st.expander("适用边界与原始规则"):
                    st.write(skill.do_not_use_when)
                    st.text(skill.body)


def capabilities():
    header(7, "能力真实可见，使用边界清晰。", "了解运行模式、数据存储与当前支持范围，再开始你的决策任务。")
    st.dataframe([
        {"能力": "业务模板", "当前状态": "可用", "说明": "三个已标注案例，确认后实际调用本机求解器"},
        {"能力": "AI 实时建模", "当前状态": "已接入", "说明": "通过统一模型服务解析需求、检索技能并建立模型；需有效服务配置"},
        {"能力": "模型确认与反馈", "当前状态": "可用", "说明": "记录确认版本；追加条件后重新建模与确认"},
        {"能力": "求解与数值验证", "当前状态": "可用", "说明": "LP / MILP；HiGHS 求解并独立重算约束、边界、整数性与目标"},
        {"能力": "任务与问题复盘", "当前状态": "可用", "说明": "本机任务库、版本对比、Badcase 跟进与报告导出"},
        {"能力": "多用户协作 / 公开部署", "当前状态": "后续规划", "说明": "当前为本地单用户平台，不提供云端协作与权限管理"},
    ], hide_index=True, width="stretch")
    st.subheader("运行与数据", anchor=False)
    st.markdown("**内置案例模式**读取已标注模型，完成确认后真实求解。**AI 模式**调用配置的模型服务，不会用静态案例替代失败结果。")
    st.markdown("任务记录保存在本机；关闭页面后可从任务记录重新打开。平台不会直接执行 AI 生成的任意 Python，实际求解读取经确认的结构化模型。")
    st.caption("服务连接由部署者在 src/config.py 配置；页面不展示 API 密钥。")
    for filename, label in [("OptiFlow-PRD.md", "产品需求文档"), ("OptiFlow-Agent-Spec.md", "能力与任务协议"), ("DEMO-GUIDE.md", "演示指南")]:
        document = Path(__file__).resolve().parents[2] / filename
        if document.exists():
            st.download_button(label, document.read_text(encoding="utf-8-sig"), file_name=filename, mime="text/markdown")


if not participant_mode or store.invite().get("experience_flow") == "workspace_v2":
    from src.workbench.workspace_ui import render
    render(store, {"queue": queue, "show_model": show_model, "show_comparison": show_comparison,
                   "records": records, "skills": skill_catalog, "capabilities": capabilities,
                   "admin": lambda: admin_page(store)})
    st.stop()

if "next_page" in st.session_state:
    st.session_state["page"] = st.session_state.pop("next_page")

if participant_mode:
    navigation = ([OVERVIEW, *PAGES[:4], COMPARE_PAGE, GUIDE_PAGE, SURVEY_PAGE, TEST_PAGE] if manual_mode
                  else [TEST_PAGE, PAGES[1], PAGES[2], PAGES[3]])
else:
    navigation = ([ADMIN_PAGE] if hosted_mode() else []) + [OVERVIEW, *PAGES, TEST_PAGE, SKILL_PAGE, CAPABILITY_PAGE]
if st.session_state.get("page") not in navigation:
    st.session_state["page"] = navigation[0]

with st.sidebar:
    st.html('<div class="brand"><div class="brand-mark">↗</div><div class="brand-name">OptiFlow</div></div>')
    st.caption("智能优化决策工作台")
    st.divider()
    st.caption("工作空间 / WORKSPACE")
    st.radio("页面导航", navigation, key="page", label_visibility="collapsed")
    st.divider()
    task = current_task()
    if task:
        st.caption("当前任务")
        st.markdown(f'**{task["title"]}**')
        st.caption(f'{STATUS.get(task["status"], task["status"])} · v{task["model_version"]}')
    st.caption("本地工作台 · MVP 1.1")
    st.caption("先确认业务模型，再执行求解。")

if manual_mode and st.session_state["page"] not in {GUIDE_PAGE, SURVEY_PAGE, TEST_PAGE}:
    manual_banner(store, go, current_task())

{OVERVIEW: lambda: participant_overview(store, go) if manual_mode else overview(), PAGES[0]: new_task, PAGES[1]: workflow, PAGES[2]: model_review,
 PAGES[3]: results, PAGES[4]: records, ADMIN_PAGE: lambda: admin_page(store),
 COMPARE_PAGE: comparison_page, GUIDE_PAGE: lambda: guide_page(store, go, current_task()),
 SURVEY_PAGE: lambda: questionnaire_page(store, go, current_task()),
 TEST_PAGE: lambda: participant_entry(store, go, queue) if participant_mode else test_entry(store, go, queue),
 SKILL_PAGE: skill_catalog, CAPABILITY_PAGE: capabilities}[st.session_state["page"]]()

if manual_mode and st.session_state["page"] not in {GUIDE_PAGE, SURVEY_PAGE, TEST_PAGE}:
    step_record(store, go, current_task())
