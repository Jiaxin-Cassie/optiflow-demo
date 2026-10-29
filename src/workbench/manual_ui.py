"""Manual-aligned study guidance, end questionnaire and organizer observation form."""
import json
from html import escape
import streamlit as st

from src.workbench.cases import CASES
from src.workbench.guidance import step_guidance
from src.workbench.manual_study import (STEPS, INTERVIEW_QUESTIONS, STEP_STATUS,
    manual_session, current_step, step_requirement, submit_step, observation, save_observation, ISSUE_STATES, save_step_note)
from src.workbench.usability import (UNDERSTANDING, DIFFICULTIES, study_for_task, finish_test,
    submit_questionnaire, test_records, export_csv)

GUIDE_PAGE = "测试任务指引"
SURVEY_PAGE = "结束问卷"
COMPARE_PAGE = "前后方案对比"


def participant_new_task(store, go, queue):
    from src.workbench.hosting import start_invited_test
    st.title("把业务问题，变成可执行的决策。")
    existing = store.invite()["task_id"]
    if existing:
        st.info("本次邀请已创建一个任务，继续使用该任务即可保留前后方案与问卷的关联。")
        if st.button("继续当前任务", type="primary"):
            st.session_state["task_id"] = existing
            go("模型查看与确认" if store.get(existing).get("model") else "Agent 工作流")
            st.rerun()
        return
    with st.container(border=True):
        st.subheader("定义一个优化任务", anchor=False)
        st.selectbox("预置业务案例", ["工厂生产计划"], disabled=True)
        st.text_area("业务需求", value=CASES["production"]["text"], height=180, disabled=True)
        st.caption("本次按测试手册使用固定案例；后续可在模型页面补充需求。模型确认后真实求解。")
        if st.button("生成可确认的模型", type="primary", width="stretch"):
            task = start_invited_test(store)
            st.session_state["task_id"] = task["task_id"]
            if task["status"] == "pending":
                queue(task, "prepare")
            go("Agent 工作流")
            st.rerun()


def participant_overview(store, go):
    st.title("让每一次业务决策，都有可检查的依据。")
    st.write("从业务需求出发，检查模型、确认求解，再比较调整前后的方案。")
    st.caption("本次使用预置的工厂生产案例，确认后真实求解；不调用实时建模服务。")
    task_id = store.invite()["task_id"]
    if st.button("打开当前任务" if task_id else "新建优化任务", type="primary"):
        go("模型查看与确认" if task_id else "新建优化任务")
        st.rerun()
    with st.container(border=True):
        st.subheader("工厂生产计划", anchor=False)
        st.write(CASES["production"]["description"])
        st.write("你将以工厂负责人的身份，完成六个连续任务。没有标准话术；请按实际理解和使用感受回答。")
    if st.button("查看本次测试任务"):
        go(GUIDE_PAGE)
        st.rerun()


def manual_banner(store, go, task):
    session = manual_session(store)
    if not session:
        return
    step = current_step(session)
    study = study_for_task(store, task["task_id"]) if task else None
    ended = study and study["status"] != "active"
    notice = st.session_state.get("manual_saved_notice")
    if notice:
        st.success(notice)
    if not step or ended:
        has_survey = bool(study and study["questionnaire"])
        st.info("问卷已提交，感谢参与。数据已保存。" if has_survey else "本次操作记录已结束，请填写最后的结束问卷。")
        if st.button("查看我的问卷" if has_survey else "填写结束问卷", key="manual_open_survey", type="primary"):
            go(SURVEY_PAGE)
            st.rerun()
        return
    key, title, _ = step
    guide = step_guidance(key, task)
    done = {r["step"] for r in session["steps"] if r["submitted_at"]}
    chips = ''.join('<span class="study-step '+('done' if k in done else 'current' if k==key else '')+'">'
                    +k+' '+escape(t)+'</span>' for k,t,_ in STEPS)
    st.html('<div class="study-steps" aria-label="六步测试进度">'+chips+'</div>')
    st.html('<div id="manual-step-guide"></div>')
    if st.session_state.get("page") in {"求解结果与验证",COMPARE_PAGE} and task and task.get("solver"):
        st.info(f"{key} · {title}：先阅读下方的决策建议，再在本页“本步记录”写下你的理解和问题。")
        st.markdown('[↓ 填写本步记录](#manual-step-record)')
        with st.expander("查看本步操作说明"):
            st.write(guide["purpose"])
            for action in guide["actions"]:
                st.write("• "+action)
        return
    with st.container(border=True, key="manual-guide"):
        st.caption(f"第 {int(key[1])} 步 / 共 6 步 · 操作说明")
        st.subheader(title, anchor=False)
        st.write(guide["purpose"])
        for index, text in enumerate(guide["actions"], 1):
            st.markdown(f"**{index}.** {text}")
        st.caption("完成本步后，在本页下方“本步记录”填写回答和遇到的问题。提交后会自动进入下一步；卡住时也可先保存问题。")
        left, right = st.columns([1, 1])
        if left.button(guide["action"], key="manual_work_action", type="primary", width="stretch"):
            go(guide["page"])
            st.rerun()
        right.markdown('[↓ 到本页下方填写本步记录](#manual-step-record)')


def step_record(store, go, task):
    session = manual_session(store)
    if not session:
        return
    step = current_step(session)
    study = study_for_task(store, task["task_id"]) if task else None
    if not step or study and study["status"] != "active":
        return
    key, title, _ = step
    guide = step_guidance(key, task)
    saved = next(r for r in session["steps"] if r["step"]==key)
    st.html('<div id="manual-step-record"></div>')
    with st.container(border=True, key="manual-record"):
        st.subheader(f"本步记录 · {key} {title}", anchor=False)
        st.markdown('[↑ 查看本步操作说明](#manual-step-guide)')
        st.write("请在这里提交本步回答和页面使用问题。记录会保存到组织者后台，不需要另发文件。")
        error = step_requirement(store, task, key)
        if error:
            st.info("本步操作还未完成："+error+" 你仍可先保存遇到的问题。")
        if saved.get("saved_at"):
            st.caption("本步已有保存的记录；提交并继续后才会标记本步结束。")
        with st.form(f"manual_step_{session['start_token']}_{key}"):
            # Keep labels stable while making the step-specific question explicit.
            st.markdown("**"+guide["question"]+"**")
            answer = st.text_area("本步回答 / 发现的问题" if key in {"T2", "T3", "T5", "T6"} else "操作感受（可选）",
                                  value=saved.get("answer") or "", placeholder=guide["placeholder"], max_chars=2000, height=110)
            issue_state = st.radio("使用网页时，本步是否遇到问题？", ISSUE_STATES,
                                   index=ISSUE_STATES.index(saved["issue_state"]) if saved.get("issue_state") in ISSUE_STATES else None)
            issue = st.text_area("问题说明（遇到问题时必填）", value=saved.get("issue") or "", max_chars=2000,
                                 placeholder="例如：找不到继续按钮、看不懂某个词、点击后没有反应。没有问题可留空。", height=90)
            help_choices = ["未获得提示", "获得提示"]
            help_report = st.radio("本步是否得到他人提示？", help_choices,
                                   index=help_choices.index(saved["help_report"]) if saved.get("help_report") in help_choices else None,
                                   horizontal=True, help="网页里的操作指引不算他人提示；这里记录的是其他人是否帮助过你。")
            a, b = st.columns(2)
            draft = a.form_submit_button("先保存问题，不结束本步", width="stretch")
            advance = b.form_submit_button("提交本步记录，进入下一步" if key!="T6" else "提交本步记录，填写结束问卷",
                                           type="primary", disabled=bool(error), width="stretch")
            if draft or advance:
                try:
                    if advance:
                        if issue_state is None:
                            raise ValueError("请选择本步是否遇到问题；没有问题也可以如实选择。")
                        submit_step(store, key, answer, help_report, expected_version=task["model_version"], issue_state=issue_state, issue=issue)
                        if key=="T6":
                            finish_test(store, study["id"])
                            go(SURVEY_PAGE)
                        else:
                            new_step = current_step(manual_session(store))[0]
                            go(step_guidance(new_step, store.get(task["task_id"]))["page"])
                        st.session_state["manual_saved_notice"] = f"{key} 的回答和问题已提交到后台。" + ("接下来请填写结束问卷。" if key=="T6" else "已进入下一步。")
                    else:
                        save_step_note(store, key, answer, help_report, issue_state=issue_state, issue=issue)
                        st.session_state["manual_saved_notice"] = f"{key} 的问题记录已保存，本步尚未结束。可以继续操作后再提交。"
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
        st.caption("本步记录与最后的体验问卷分开保存。步骤经过时间可能包含等待和离开页面，不当作实测操作耗时。")
    if study:
        with st.expander("确实无法继续，结束本次测试"):
            st.write("建议先保存本步问题，再结束为未完成；已有记录会保留，仍可填写最后的问卷。")
            if st.button("结束为未完成并填写问卷"):
                finish_test(store, study["id"], interrupted=True)
                go(SURVEY_PAGE)
                st.rerun()


def guide_page(store, go, task):
    st.title("测试说明与问题记录")
    st.write("你将完成六步体验。每一步都先看上方说明，在工作台操作，然后在同一页下方“本步记录”填写并提交。最后再填写结束问卷。")
    session = manual_session(store)
    if not session:
        st.info("请先在可用性测试入口开始本次体验。")
        return
    manual_banner(store, go, task)
    with st.expander("查看测试手册中的六个任务"):
        for key,title,prompt in STEPS:
            st.markdown(f"**{key} {title}**")
            st.write(prompt)
    with st.expander("查看我已保存的回答和问题"):
        st.dataframe([{"步骤":r["step"],"状态":"已提交" if r["submitted_at"] else "未提交 / 草稿",
                       "本步回答":r.get("answer") or "", "网页使用问题":r.get("issue") or "",
                       "问题自报":r.get("issue_state") or ""} for r in session["steps"]], hide_index=True, width="stretch")
    step_record(store, go, task)


def questionnaire_page(store, go, task):
    st.title("结束问卷")
    if not task:
        st.info("请先从测试入口开始体验。")
        return
    study = study_for_task(store, task["task_id"])
    session = manual_session(store)
    if not study or not session:
        st.info("该记录使用原版测试，请在结果页提交对应的简短评价。")
        return
    if study["status"] == "active":
        st.info("请先记录 T1–T6；若无法继续，也可以在测试指引中结束为未完成。")
        if st.button("返回测试任务指引"):
            go(GUIDE_PAGE)
            st.rerun()
        return
    st.caption(f"匿名编号 {study['participant_id']} · 操作{'已完成' if study['status']=='completed' else '未完成'} · 不要求填写姓名或联系方式。")
    previous = json.loads(study["questionnaire"]) if study["questionnaire"] else {}
    if previous:
        st.success("问卷已提交，组织者已可在后台查看和导出。无需另发文件。")
        st.caption("如需修正，可以再次提交；系统保留提交记录。")
    else:
        st.write("以下问题来自本次测试手册。请按实际体验回答，可以如实写“没有”或“不确定”。提交后自动保存到组织者的后台。")
    with st.form(f"manual_questionnaire_{study['id']}"):
        understanding = st.radio("你是否能理解系统生成的业务模型？", UNDERSTANDING,
                                  index=UNDERSTANDING.index(previous["understanding"]) if previous.get("understanding") in UNDERSTANDING else None)
        difficulty = st.selectbox("你觉得哪个环节最困难？", DIFFICULTIES,
                                  index=DIFFICULTIES.index(previous["difficulty"]) if previous.get("difficulty") in DIFFICULTIES else None)
        other = st.text_input("其他困难（选择其他时填写）", value=previous.get("difficulty_other", ""), max_chars=1000)
        answers = {}
        for key, question in INTERVIEW_QUESTIONS:
            answers[key] = st.text_area(question, value=previous.get("interview", {}).get(key, ""), max_chars=2000, height=110)
        if st.form_submit_button("提交结束问卷", type="primary"):
            try:
                submit_questionnaire(store, study["id"], understanding, difficulty, interview=answers, difficulty_other=other)
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
    if previous:
        st.download_button("下载我的测试与问卷 CSV", export_csv(test_records(store)), file_name="my-optiflow-study.csv", mime="text/csv")
    if st.button("返回查看生产决策建议"):
        go("求解结果与验证")
        st.rerun()


def organizer_record(store, row):
    """Observer fields stay manager-only, separate from participant responses."""
    selected = row["test_id"]
    if row.get("protocol") == "workspace_v2":
        with st.expander("查看新版体验反馈", expanded=True):
            st.caption(f"匿名编号 {row['participant_id']} · 问卷版本：{row['questionnaire_version'] or '未提交'}")
            for key, label in [("ease", "容易上手（1–5）"), ("clarity", "下一步清晰度（1–5）"),
                               ("confusing_stage", "最困惑环节"), ("had_problem", "是否遇到问题"),
                               ("problem", "问题说明"), ("improvement", "改进建议"), ("questionnaire_submitted_at", "提交时间")]:
                st.write(label+"："+str(row.get(key, "")))
        return
    with st.expander("查看手册回答与填写观察记录"):
        st.caption(f"匿名编号 {row['participant_id']} · 背景：{row.get('background') or '未记录'} · 测试协议：{row.get('protocol', 'legacy')}")
        st.dataframe([{"任务": f"{key} {title}", "参与者已记录": row.get(f"{key}_submitted", False),
                       "回答原文": row.get(f"{key}_answer", ""), "网页遇到的问题": row.get(f"{key}_issue", ""), "问题自报": row.get(f"{key}_issue_state", ""), "提示（自报）": row.get(f"{key}_help_self_report", ""),
                       "经过时间（秒）": row.get(f"{key}_elapsed_seconds")} for key, title, _ in STEPS], hide_index=True, width="stretch")
        st.write("问卷提交：" + (row.get("questionnaire_submitted_at") or "未提交"))
        st.write("理解度：" + row.get("understanding", ""))
        st.write("最困难环节：" + row.get("difficulty", "") + " " + row.get("difficulty_other", ""))
        for key, label in INTERVIEW_QUESTIONS:
            st.markdown(f"**{label}**")
            st.write(row.get(key) or "未作答")
        saved = observation(store, selected)
        st.caption("以下由观察者填写。未经观察的任务保留“未测试”，不可将点击记录自动视为独立完成。耗时留空表示未测量。")
        with st.form(f"observer_{selected}"):
            steps = {}
            for key, title, _ in STEPS:
                original = saved.get("steps", {}).get(key, {})
                st.markdown(f"**{key} {title}**")
                a, b = st.columns(2)
                status = a.selectbox("观察到的完成情况", STEP_STATUS, index=STEP_STATUS.index(original.get("status", "未测试")), key=f"observer_status_{selected}_{key}")
                seconds = b.number_input("实测耗时（秒，可留空）", min_value=0.0, max_value=86400.0, value=original.get("seconds"), key=f"observer_seconds_{selected}_{key}")
                issue = st.text_area("发现问题", value=original.get("issue", ""), max_chars=2000, key=f"observer_issue_{selected}_{key}")
                steps[key] = {"status": status, "seconds": seconds, "issue": issue}
            payload = {"steps": steps}
            for key, label in [("technical_issues", "关键异常 / 技术问题（发生时间、步骤、错误信息）"), ("severe_issue", "最严重问题"),
                               ("impact", "影响"), ("hypothesis", "可能原因（假设）")]:
                payload[key] = st.text_area(label, value=saved.get(key, ""), max_chars=3000)
            if st.form_submit_button("保存观察记录"):
                try:
                    save_observation(store, selected, payload)
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
