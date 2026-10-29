"""Small Streamlit views for local anonymous usability sessions."""
from uuid import uuid4
import streamlit as st

from src.workbench.cases import CASES
from src.workbench.explanations import decision_summary
from src.workbench.usability import (UNDERSTANDING, DIFFICULTIES, ASSESSMENTS, start_test, study_for_task,
    finish_test, submit_questionnaire, test_records, summarize_tests, export_csv, assess_discovery, delete_test)


def test_entry(store, go, queue):
    st.title("可用性测试")
    st.caption("独立于普通任务：使用匿名编号体验模型复核、需求反馈与决策理解。无需模型 API。")
    st.caption("提取数据：任务记录与 Badcase → 可用性测试汇总 → 导出可用性测试 CSV。")
    with st.form("study_start"):
        participant = st.text_input("匿名参与者编号", placeholder="例如 P001，不填写姓名或联系方式", max_chars=32)
        case_id = st.selectbox("测试案例", list(CASES), format_func=lambda k: CASES[k]["title"])
        with st.expander("测试设计者：预定义错误判定标准（可选）"):
            st.caption("标准在测试开始时固定。系统不会自动向案例植入错误；无标准的记录不计算错误发现率。")
            standard = st.text_area("预定义核查标准", max_chars=500)
        if st.form_submit_button("开始 / 继续测试", type="primary"):
            tokens = st.session_state.setdefault("study_start_tokens", {})
            token = tokens.setdefault((participant.strip(), case_id), uuid4().hex)
            try:
                task = start_test(store, participant.strip(), case_id, token, standard)
                st.session_state["task_id"] = task["task_id"]
                if task["status"] == "pending":
                    queue(task, "prepare")
                go("模型查看与确认" if task.get("model") else "Agent 工作流")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
    st.caption("同一匿名编号与案例存在进行中的测试时会继续原记录；离开页面不会被自动统计为完成。")
    if st.button("准备开始另一次测试"):
        st.session_state["study_start_tokens"] = {}
        st.success("已更新启动标识；同编号的未结束测试仍会优先恢复。")


def study_controls(store, task):
    study = study_for_task(store, task["task_id"])
    if not study:
        return
    from src.workbench.manual_study import manual_session
    if manual_session(store, task["task_id"]):
        from src.workbench.manual_ui import GUIDE_PAGE, SURVEY_PAGE
        st.caption("请在本页下方“本步记录”提交回答和遇到的问题；提交后自动进入下一步，最后填写结束问卷。")
        return
    with st.container(border=True):
        st.subheader("本次可用性测试", anchor=False)
        st.caption(f"匿名编号 {study['participant_id']} · 案例 {study['case_id']} · 测试状态 {study['status']}")
        if study["status"] == "active":
            a, b = st.columns(2)
            if a.button("标记测试完成", key=f"finish_{study['id']}", type="primary", disabled=not decision_summary(task)["eligible"]):
                try:
                    finish_test(store, study["id"])
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
            if b.button("结束为未完成", key=f"interrupt_{study['id']}"):
                finish_test(store, study["id"], interrupted=True)
                st.rerun()
            st.caption("查看有效结果后由你标记完成；也可结束为未完成。主观评价不影响求解状态。")
        else:
            st.success("测试已完成。" if study["status"] == "completed" else "测试已结束，保留为未完成记录。")
            st.caption(f"评价对应本次测试结束的模型版本 v{study['ended_version']}。")
            st.caption("问卷已提交" if study["questionnaire"] else "问卷未提交，可跳过体验评价。")
            if getattr(store, "participant_hash", None):
                st.caption("数据已自动保存到组织者的服务器，无需手工发送。下面只可导出你自己的记录。")
                st.download_button("下载我的测试记录 CSV", export_csv(test_records(store)), file_name="my-optiflow-study.csv", mime="text/csv")
            else:
                st.caption("记录可在“任务记录与 Badcase → 可用性测试汇总”中查看或导出。")
            with st.form(f"survey_{study['id']}"):
                understanding = st.radio("你是否能理解系统生成的业务模型？", UNDERSTANDING, index=None)
                difficulty = st.selectbox("你觉得哪个环节最困难？", DIFFICULTIES, index=None)
                comment = st.text_area("你觉得哪里可以改进？（可选）", max_chars=1000)
                if st.form_submit_button("提交体验评价"):
                    try:
                        submit_questionnaire(store, study["id"], understanding, difficulty, comment)
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))


def test_summary(store):
    from src.workbench.hosting import require_manager
    require_manager(store)
    all_rows = test_records(store)
    protocols = sorted({r["protocol"] for r in all_rows})
    protocol = st.selectbox("按体验协议查看统计", protocols, index=protocols.index("workspace_v2") if "workspace_v2" in protocols else 0) if protocols else None
    rows = [r for r in all_rows if r["protocol"] == protocol]
    channels = sorted({r["experience_channel"] for r in rows})
    if channels:
        channel = st.selectbox("记录来源", channels, index=channels.index("invited") if "invited" in channels else 0,
                               format_func=lambda k: {"invited": "专属邀请体验", "local": "本机体验", "public_demo": "公开演示", "historical_unlabeled": "历史记录（未标注来源）"}[k])
        rows = [r for r in rows if r["experience_channel"] == channel]
    st.caption("不同体验协议分别统计，避免把六任务手册与新版工作台的完成率混算。")
    if all_rows:
        st.download_button("导出全部协议原始记录 CSV", export_csv(all_rows), file_name="optiflow-all-usability.csv", mime="text/csv")
    metrics = summarize_tests(rows)
    st.caption("下列指标统计已创建专用任务的匿名测试记录，不是商业用户增长。普通任务不进入分母；开始 T1 后尚未创建任务的人另列。")
    from src.workbench.manual_study import enrollment_records
    enrolled = enrollment_records(store)
    if enrolled:
        with st.expander(f"六任务开始记录（含 T1 尚未创建任务）：{len(enrolled)} 人"):
            st.dataframe(enrolled, hide_index=True, width="stretch")
            import csv
            import io
            handle = io.StringIO(newline="")
            writer = csv.DictWriter(handle, ["participant_id", "protocol", "background", "started_at", "task_id", "T1_issue_state", "T1_issue", "T1_note_saved_at"])
            writer.writeheader()
            writer.writerows({k:("'"+v if isinstance(v,str) and v.startswith(("=","+","-","@","\t","\r")) else v) for k,v in r.items()} for r in enrolled)
            st.download_button("导出六任务开始记录 CSV", handle.getvalue().encode("utf-8-sig"), file_name="optiflow-manual-starts.csv", mime="text/csv")
    a, b, c, d = st.columns(4)
    a.metric("有效参与记录", metrics["started"])
    b.metric("完成测试", f"{metrics['completed']} / {metrics['started']}")
    c.metric("任务完成率", f"{metrics['completion_rate']:.1%}" if rows else "—")
    d.metric("平均审核时间", f"{metrics['review_mean_seconds']:.1f} s" if metrics["review_mean_seconds"] is not None else "—")
    st.caption("审核时间起点：首次打开模型确认页；终点：首次有效确认，未确认但已结束则取结束时间。未进入审核或仍在审核的记录不填 0。")
    st.write(f"反馈提交率：{metrics['feedback_count']} / {metrics['started']}；模型确认率：{metrics['confirmation_count']} / {metrics['started']}。")
    st.write(f"问卷已提交：{sum(r['questionnaire_submitted'] for r in rows)} / {metrics['started']}。操作完成与问卷提交分别统计。")
    if metrics["assessed_count"]:
        st.write(f"人工评定的错误发现率：{metrics['discovery_count']} / {metrics['assessed_count']}（{metrics['discovery_rate']:.1%}）；分母仅含有预定义标准且已评定的记录。")
    else:
        st.info("尚无具备预定义标准的人工评定，不显示错误发现率。反馈提交不等于正确发现错误。")
    if not rows:
        st.info("暂无测试记录。请从“可用性测试”入口邀请参与者开始操作。")
        return
    a, b = st.columns(2)
    a.dataframe([{"理解度": k, "记录数": v} for k, v in metrics["understanding"].items()], hide_index=True)
    b.dataframe([{"困难环节": k, "记录数": v} for k, v in metrics["difficulty"].items()], hide_index=True)
    summary_fields = ["participant_id", "case_id", "protocol", "background", "status", "model_version", "questionnaire_submitted", "understanding", "difficulty", "ease", "clarity", "confusing_stage", "had_problem"]
    st.dataframe([{k: r.get(k) for k in summary_fields} for r in rows], hide_index=True, width="stretch")
    st.download_button("导出可用性测试 CSV", export_csv(rows), file_name="optiflow-usability.csv", mime="text/csv")
    st.caption("CSV 包含六步回答、经过时间、问卷原文与观察者记录；经过时间含等待与离开页面，不能当作实测操作耗时。")
    selected_details = st.selectbox("查看参与者回答与问卷", [r["test_id"] for r in rows],
                                   format_func=lambda k: next(f"{r['participant_id']} · {r['case_id']} · {k[:8]}" for r in rows if r["test_id"] == k))
    from src.workbench.manual_ui import organizer_record
    organizer_record(store, next(r for r in rows if r["test_id"] == selected_details))
    with st.expander("测试设计者：人工评定与数据删除"):
        selected = st.selectbox("选择测试记录", [r["test_id"] for r in rows],
                                format_func=lambda k: next(f"{r['participant_id']} · {r['case_id']} · {k[:8]}" for r in rows if r["test_id"] == k))
        row = next(r for r in rows if r["test_id"] == selected)
        st.write("预定义标准：" + (row["error_standard"] or "未定义"))
        st.caption("评定须人工核对参与者反馈与标准；当前不提供自动正确性判定。可从任务记录打开对应任务查看反馈。")
        label = st.selectbox("错误发现标签", ASSESSMENTS, index=ASSESSMENTS.index(row["assessment"]), key=f"assess_{selected}")
        if st.button("保存人工评定"):
            try:
                assess_discovery(store, selected, label)
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
        consent = st.checkbox("删除这条测试及其专用任务、问卷、事件和运行文件（普通任务不受影响）", key=f"delete_study_{selected}")
        if st.button("删除测试数据", disabled=not consent):
            try:
                delete_test(store, selected)
                st.rerun()
            except (ValueError, OSError):
                st.error("请确认任务已停止处理且运行文件可访问后，再删除测试数据。")
