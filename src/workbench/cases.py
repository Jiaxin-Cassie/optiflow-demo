"""Explicit, deterministic business fixtures; never substituted for live input."""
from copy import deepcopy
import math
import re

from src.workbench.model import ModelError


def _production():
    text = ("某工厂生产 A、B 两类产品。A 每件利润 40 元，B 每件利润 30 元。"
            "每件 A 消耗 2 小时人工、1 小时机器，每件 B 消耗 1 小时人工、2 小时机器。"
            "可用人工 400 小时、机器 500 小时。产量为非负整数。请安排生产数量，使总利润最大。")
    model = {"kind": "MILP", "variables": [
        {"name": name, "label": f"产品 {name} 产量", "unit": "件", "domain": "integer",
         "lower": 0, "upper": None, "source": "产量为非负整数。"} for name in ("A", "B")],
        "objective": {"label": "总利润", "sense": "max", "coefficients": {"A": 40, "B": 30}, "constant": 0,
                      "unit": "元", "source": "A 每件利润 40 元，B 每件利润 30 元。"},
        "constraints": [
            {"id": "labor", "label": "人工工时", "coefficients": {"A": 2, "B": 1}, "relation": "<=", "rhs": 400,
             "source": "每件 A 消耗 2 小时人工、1 小时机器，每件 B 消耗 1 小时人工、2 小时机器。"},
            {"id": "machine", "label": "机器工时", "coefficients": {"A": 1, "B": 2}, "relation": "<=", "rhs": 500,
             "source": "可用人工 400 小时、机器 500 小时。"}],
        "assumptions": ["利润与资源消耗按产量线性累加，无固定开机成本。"], "missing_inputs": []}
    return {"id": "production", "title": "工厂生产计划", "category": "生产计划", "icon": "factory",
            "description": "在人工与机器工时限制下，安排两种产品的产量。", "text": text, "model": model}


def _allocation():
    text = ("将预算分配给搜索广告和信息流广告。每单位搜索广告成本 3 千元，预计带来 5 个有效线索；"
            "每单位信息流广告成本 2 千元，预计带来 3 个有效线索。总预算 120 千元。"
            "搜索广告最多投放 30 单位，信息流广告至少投放 10 单位。投放单位为非负整数。最大化有效线索总量。")
    model = {"kind": "MILP", "variables": [
        {"name": "search", "label": "搜索广告", "unit": "单位", "domain": "integer", "lower": 0, "upper": 30,
         "source": "搜索广告最多投放 30 单位，信息流广告至少投放 10 单位。"},
        {"name": "feed", "label": "信息流广告", "unit": "单位", "domain": "integer", "lower": 10, "upper": None,
         "source": "搜索广告最多投放 30 单位，信息流广告至少投放 10 单位。"}],
        "objective": {"label": "预计有效线索", "sense": "max", "coefficients": {"search": 5, "feed": 3}, "constant": 0,
                      "unit": "个", "source": "每单位搜索广告成本 3 千元，预计带来 5 个有效线索；每单位信息流广告成本 2 千元，预计带来 3 个有效线索。"},
        "constraints": [{"id": "budget", "label": "广告总预算", "coefficients": {"search": 3, "feed": 2},
                         "relation": "<=", "rhs": 120, "source": "总预算 120 千元。"}],
        "assumptions": ["各渠道线索数为固定预测，不包含边际衰减与渠道重叠。"], "missing_inputs": []}
    return {"id": "allocation", "title": "营销预算分配", "category": "资源分配", "icon": "chart",
            "description": "在预算和渠道投放边界内，获取更多有效线索。", "text": text, "model": model}


def _staffing():
    text = ("客服团队安排白班和晚班。白班每人每天成本 200 元，晚班每人每天成本 260 元。"
            "白班至少需要 8 人，晚班至少需要 5 人。每日可用客服总数不超过 16 人。"
            "排班人数为非负整数。最小化每日人力成本。")
    model = {"kind": "MILP", "variables": [
        {"name": "day", "label": "白班人数", "unit": "人", "domain": "integer", "lower": 8, "upper": None,
         "source": "白班至少需要 8 人，晚班至少需要 5 人。"},
        {"name": "night", "label": "晚班人数", "unit": "人", "domain": "integer", "lower": 5, "upper": None,
         "source": "白班至少需要 8 人，晚班至少需要 5 人。"}],
        "objective": {"label": "每日人力成本", "sense": "min", "coefficients": {"day": 200, "night": 260}, "constant": 0,
                      "unit": "元", "source": "白班每人每天成本 200 元，晚班每人每天成本 260 元。"},
        "constraints": [{"id": "headcount", "label": "可用客服人数", "coefficients": {"day": 1, "night": 1},
                         "relation": "<=", "rhs": 16, "source": "每日可用客服总数不超过 16 人。"}],
        "assumptions": ["客服能力一致，无跨日连续排班或工时限制。"], "missing_inputs": []}
    return {"id": "staffing", "title": "客服人力排班", "category": "人员排班", "icon": "people",
            "description": "满足两班最低人员需求，控制每日人力成本。", "text": text, "model": model}


CASES = {case["id"]: case for case in (_production(), _allocation(), _staffing())}


def parse_case_feedback(case_id, note):
    """Accept common single-bound wording while rejecting ambiguous extra requests."""
    if case_id not in CASES or not isinstance(note, str):
        raise ModelError("请选择有效案例并填写补充需求。")
    prefix = r"(?:(?:请)?(?:新增|增加|添加|补充)(?:一(?:条|个))?(?:约束|需求|要求|条件|限制)[：:]?\s*)?"
    pattern = (prefix + r"(?:产品\s*)?(?P<name>[A-Za-z][A-Za-z0-9_]*)\s*(?:产品)?\s*(?:的)?\s*(?:每天|每日)?\s*"
               r"(?:产量|投放量|人数)?\s*(?P<relation>不能超过|不得超过|不超过|不多于|最多(?:只能)?(?:生产)?|上限为|至少(?:生产)?|最少(?:生产)?|不少于|不低于|>=|<=|==|等于)\s*"
               r"(?P<rhs>\d+(?:\.\d+)?)\s*(?P<unit>件|人|单位)?\s*(?:(?:的)?(?:新)?(?:要求|需求|约束|限制|条件))?[。.!！]?")
    match = re.fullmatch(pattern, note.strip())
    if not match:
        raise ModelError("这条需求还未识别，输入已保留。可写“A 每天最多生产 100 件”，或使用“选择产品和数量”。一次请只补充一条数量限制。")
    name, relation, rhs, unit = match.group("name", "relation", "rhs", "unit")
    variables = CASES[case_id]["model"]["variables"]
    matches = [v for v in variables if v["name"] == name] or [v for v in variables if v["name"].casefold() == name.casefold()]
    if len(matches) != 1:
        raise ModelError("没有找到对应的决策项，请使用页面中的名称，或改用“选择产品和数量”。")
    variable = matches[0]
    if unit and variable.get("unit") and unit != variable["unit"]:
        raise ModelError(f"数量单位应为“{variable['unit']}”，请核对后再提交。")
    relation = ">=" if relation.startswith(("至少", "最少")) or relation in {"不少于", "不低于", ">="} else "==" if relation in {"==", "等于"} else "<="
    if not math.isfinite(float(rhs)):
        raise ModelError("数量过大，请使用有限数值并核对单位。")
    return {"name": variable["name"], "label": variable["label"], "relation": relation, "rhs": float(rhs), "unit": variable.get("unit", "")}


def case_model(case_id, text, feedback=()):
    case = CASES.get(case_id)
    if not case or text != case["text"]:
        raise ModelError("内置案例模式只处理预置需求；自定义问题请选择 AI 实时建模。")
    model = deepcopy(case["model"])
    for index, note in enumerate(feedback):
        parsed = parse_case_feedback(case_id, note)
        name, relation, rhs = parsed["name"], parsed["relation"], parsed["rhs"]
        label=parsed["label"]+{"<=":" · 数量上限",">=":" · 数量下限","==":" · 固定数量"}[relation]
        model["constraints"].append({"id": f"feedback_{index + 1}", "label": label,
                                     "coefficients": {name: 1}, "relation": relation, "rhs": float(rhs), "source": note})
    return model

