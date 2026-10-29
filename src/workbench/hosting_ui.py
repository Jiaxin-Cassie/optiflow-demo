"""Online study gate and a single password-protected research management view."""
import csv
import hashlib
import io
import os
import time

import streamlit as st

from src.workbench.cases import CASES
from src.workbench.hosting import (hosted_mode, admin_secret, authenticate_admin, ParticipantStore,
    create_invites, list_invites, revoke_invite, start_invited_test)
from src.workbench.study_ui import test_summary


def _admin_login():
    previous = st.session_state.get("admin_attempts", [])
    recent = [t for t in previous if time.monotonic() - t < 60]
    password = st.session_state.pop("admin_login_input", "")
    if len(recent) >= 5:
        st.session_state["admin_login_error"] = "本会话尝试过于频繁，请稍后再试。"
        return
    st.session_state["admin_attempts"] = [*recent, time.monotonic()]
    if authenticate_admin(password):
        st.session_state["study_admin_auth"] = hashlib.sha256(admin_secret().encode()).hexdigest()
        st.session_state.pop("admin_login_error", None)
    else:
        st.session_state["admin_login_error"] = "管理员口令不正确。"


def _scope(identifier):
    if st.session_state.get("access_scope") != identifier:
        for key in ("task_id", "page", "next_page", "workflow_rendered_status", "manual_saved_notice", "of_view", "of_step", "of_modify", "of_feedback_saved"):
            st.session_state.pop(key, None)
        st.session_state["access_scope"] = identifier


def access_gate(store):
    from src.workbench.public_demo import public_demo_mode, visitor_store
    if public_demo_mode() and st.query_params.get("admin") != "1":
        secret = st.session_state.get("demo_visitor_secret")
        try:
            scoped, secret = visitor_store(store, secret)
        except PermissionError:
            scoped, secret = visitor_store(store)
        st.session_state["demo_visitor_secret"] = secret
        invite = scoped.invite()
        _scope(invite["id"])
        if invite["task_id"]:
            st.session_state["task_id"] = invite["task_id"]
        return scoped
    if not hosted_mode():
        return store
    try:
        expected = hashlib.sha256(admin_secret().encode()).hexdigest()
    except ValueError:
        st.info("公开演示未启用管理后台。" if public_demo_mode() else "在线测试服务尚未配置管理员口令，请联系部署者。")
        st.stop()
    if st.query_params.get("admin") == "1":
        if st.session_state.get("study_admin_auth") != expected:
            st.title("测试管理员登录")
            st.caption("登录后可创建参与者邀请、查看全部记录并统一导出。")
            with st.form("study_admin_login"):
                st.text_input("管理员口令", type="password", key="admin_login_input")
                st.form_submit_button("进入管理后台", on_click=_admin_login)
            if st.session_state.get("admin_login_error"):
                st.error(st.session_state["admin_login_error"])
            st.stop()
        _scope("administrator")
        return store
    secret = st.query_params.get("invite", "")
    if not secret:
        st.title("OptiFlow · 在线用户测试")
        st.write("请使用测试组织者发给你的专属邀请链接。无需下载项目或安装软件。")
        st.caption("测试数据统一保存在服务器，你只能查看自己的测试；组织者可在管理后台统一导出。")
        st.stop()
    try:
        scoped = ParticipantStore(store.path, secret)
        invite = scoped.invite()
    except (PermissionError, ValueError):
        st.error("邀请链接无效或已撤销，请联系测试组织者。")
        st.stop()
    _scope(invite["id"])
    if invite["task_id"]:
        st.session_state["task_id"] = invite["task_id"]
    return scoped


def participant_entry(store, go, queue):
    invite = store.invite()
    from src.workbench.manual_study import begin_manual, manual_session, BACKGROUNDS
    from src.workbench.manual_ui import SURVEY_PAGE
    session = manual_session(store)
    st.title("参与 OptiFlow 测试")
    st.write(f"匿名编号：{invite['participant_id']} · 案例：{CASES[invite['case_id']]['title']}")
    st.caption("你的操作和问卷会自动保存到同一台服务器，不需要把文件发给组织者。请保留专属链接以便继续；不要转发给其他人。")
    if invite["case_id"] == "production" and (session or not invite["task_id"]):
        st.write("本次按照测试手册完成六个连续任务：开始制定生产计划、检查理解与遗漏、补充新要求、查看建议、比较前后方案，最后填写结束问卷。")
        st.caption("平台记录你的操作、各步回答和问卷。独立完成情况与实测耗时由组织者另外观察记录。")
        st.info("不用懂优化知识。每步按页面上方说明操作，再到同一页下方“本步记录”填写回答和遇到的问题；提交后自动进入下一步。卡住也可以先保存问题，最后另填结束问卷。")
        if session:
            if st.button("继续六任务体验", type="primary"):
                from src.workbench.manual_study import current_step
                go("工作台总览" if current_step(session) else SURVEY_PAGE)
                st.rerun()
        else:
            with st.form("manual_study_begin"):
                background = st.radio("你对优化的了解程度", BACKGROUNDS, index=None)
                if st.form_submit_button("开始六任务体验", type="primary"):
                    try:
                        begin_manual(store, background)
                        go("工作台总览")
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))
        return
    st.caption("此邀请沿用原版案例体验；新建工厂生产邀请使用手册中的六任务流程。")
    if st.button("开始 / 继续我的测试", type="primary"):
        try:
            task = start_invited_test(store)
            st.session_state["task_id"] = task["task_id"]
            if task["status"] == "pending":
                queue(task, "prepare")
            go("模型查看与确认" if task.get("model") else "Agent 工作流")
            st.rerun()
        except (ValueError, PermissionError):
            st.error("无法继续该测试，请刷新链接或联系组织者。")


def admin_page(store):
    from src.workbench.public_demo import public_demo_mode
    if public_demo_mode():
        st.title("演示反馈管理")
        st.caption("这里只包含公开演示实例的记录，与正式受邀测试数据分开。")
        test_summary(store)
        if st.button("退出管理员登录"):
            st.session_state.pop("study_admin_auth", None)
            st.rerun()
        return
    st.title("测试管理后台")
    st.caption("异地参与者使用各自邀请链接；本页查看和导出同一服务数据库中的全部记录。")
    invites_tab, records_tab = st.tabs(["参与者邀请", "全量数据与导出"])
    with invites_tab:
        st.caption("新邀请默认使用四阶段工作台与独立体验反馈。历史邀请和问卷保留原协议，统计时请区分流程版本。")
        st.info("首次创建后请立即保存链接。数据库只保存邀请令牌的哈希，无法再次显示原链接；丢失时撤销旧邀请并创建新的邀请。")
        with st.form("create_hosted_invites"):
            base_url = st.text_input("服务公网地址", value=os.environ.get("OPTIFLOW_PUBLIC_URL", ""), placeholder="https://study.example.com")
            case_id = st.selectbox("分配的测试案例", list(CASES), format_func=lambda k: CASES[k]["title"])
            count = st.number_input("邀请数量", min_value=1, max_value=50, value=5, step=1)
            experience_flow = st.selectbox("体验流程", ["workspace_v2", "legacy"],
                format_func=lambda k: "新版工作台 + 独立体验反馈" if k == "workspace_v2" else "历史手册流程（用于原测试队列）")
            standard = st.text_area("预定义错误核查标准（可选）", max_chars=500)
            if st.form_submit_button("创建专属邀请"):
                try:
                    st.session_state["new_invites"] = create_invites(store, case_id, int(count), base_url, standard, experience_flow=experience_flow)
                except ValueError as exc:
                    st.error(str(exc))
        new = st.session_state.get("new_invites")
        if new:
            st.dataframe(new, hide_index=True, width="stretch")
            handle = io.StringIO(newline="")
            writer = csv.DictWriter(handle, ["invite_id", "participant_id", "case_id", "url"])
            writer.writeheader()
            writer.writerows(new)
            st.download_button("下载邀请链接 CSV（请妥善保存）", handle.getvalue().encode("utf-8-sig"), file_name="optiflow-invitations.csv", mime="text/csv")
        invitations = list_invites(store)
        if invitations:
            st.dataframe(invitations, hide_index=True, width="stretch")
            active = [r for r in invitations if not r["revoked_at"]]
            if active:
                selected = st.selectbox("撤销邀请", [r["id"] for r in active], format_func=lambda k: next(r["participant_id"] for r in active if r["id"] == k))
                if st.button("撤销所选邀请"):
                    revoke_invite(store, selected)
                    st.session_state.pop("new_invites", None)
                    st.rerun()
    with records_tab:
        test_summary(store)
    if st.button("退出管理员登录"):
        st.session_state.pop("study_admin_auth", None)
        st.session_state.pop("new_invites", None)
        st.rerun()
