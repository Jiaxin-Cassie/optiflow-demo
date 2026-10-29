"""Reviewable model alignment and prominent, solver-backed decision advice."""
import streamlit as st
from src.workbench.explanations import fmt
from src.workbench.review import model_alignment,decision_brief


def alignment_panel(task):
    alignment=model_alignment(task)
    previous=alignment["previous_version"]
    if previous:
        counts=alignment["counts"]
        st.subheader(f"这次改了什么？v{previous} → v{task['model_version']}",anchor=False)
        st.write(f"新增 {counts['新增']} 项 · 修改 {counts['已修改']} 项 · 移除 {counts['已移除']} 项 · 保持不变 {counts['保持不变']} 项")
        st.info("你补充的需求："+alignment["revision_note"])
        st.caption("模型规则变化与求解结果变化分别展示。新增限制后，需要重新确认并计算，结果也可能保持不变。")
    else:
        st.subheader("从业务需求，到系统模型",anchor=False)
        st.caption("这里对照你的业务情况与系统生成的规则。请核对含义、数值和假设；发现遗漏时可以补充需求。")
    for row in alignment["rows"]:
        with st.container(border=True):
            if row["status"]=="新增":
                st.success("新增规则 · "+row["label"])
            elif row["status"] in {"已修改","已移除"}:
                st.warning(row["status"]+" · "+row["label"])
            else:
                st.markdown(f"**{row['kind']} · {row['label']}**　{row['status']}")
            original,modeled=st.columns(2,gap="large")
            with original:
                st.caption("业务原文 / 你的补充")
                st.write(row["source"] or "未提供对应原文，请核对建模假设。")
            with modeled:
                st.caption("系统转成的规则")
                st.write(row["meaning"])
                if row["status"]=="已修改" and row["before"]:
                    st.caption("修改前："+row["before"]["meaning"])
                with st.expander("对应数学表达"):
                    st.code(row["formula"],language=None)
    if task["model"].get("assumptions"):
        st.caption("模型另有假设，请在确认前核对：")
        for assumption in task["model"]["assumptions"]:
            st.write("• "+assumption)


def decision_panel(task,*,key="result",resource_summary=False):
    brief=decision_brief(task)
    with st.container(border=True,key="decision-brief-"+key):
        st.subheader("本次生产决策建议" if task.get("case_id")=="production" else "本次决策建议",anchor=False)
        if not brief["eligible"]:
            st.warning(brief["next_step"])
            return brief
        st.markdown("**"+brief["recommendation"]+"**")
        st.write("**执行建议：** "+brief["actions"][0])
        columns=st.columns(min(len(brief["decision_rows"])+1,4))
        for i,row in enumerate(brief["decision_rows"]):
            columns[i%len(columns)].metric(row["label"],fmt(row["value"])+" "+row["unit"])
        obj=task["model"]["objective"]
        columns[-1].metric(obj.get("label","目标值"),f"{task['solver']['objective_value']:,.2f} "+obj.get("unit",""))
        st.write("**为什么这样安排？** 在当前已确认的规则下，求解器报告该组合为最优，且独立数值检查通过。")
        if resource_summary and brief["resource_rows"]:
            st.write("**主要限制用量：** "+"；".join(f"{r['规则']} {fmt(r['本方案用量'])} / 上限 {fmt(r['上限'])}" for r in brief["resource_rows"][:3])+"。")
        if brief["change_explanation"]:
            st.info(brief["change_explanation"])
        st.caption(brief["limitations"])
        with st.expander("查看目标、资源使用和数量上限依据"):
            st.write(brief["objective_summary"])
            if brief["resource_rows"]:
                st.dataframe(brief["resource_rows"],hide_index=True,width="stretch")
    return brief
