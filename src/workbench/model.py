"""Strict, executable LP/MILP contract. No expressions are evaluated as code."""
import math
import re


class ModelError(ValueError):
    pass


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ModelError("模型系数必须为有限数值。")
    if abs(value) > 1e12:
        raise ModelError("数值超过 MVP 支持范围（绝对值 1e12）。")
    return float(value)


def validate_model(model, problem_text):
    """Validate the data contract, including literal provenance and bounded size."""
    if not isinstance(model, dict) or model.get("kind") not in {"LP", "MILP"}:
        raise ModelError("当前工作台只支持 LP / MILP；请拆分或调整非线性问题。")
    variables = model.get("variables")
    constraints = model.get("constraints")
    if not isinstance(variables, list) or not 1 <= len(variables) <= 200:
        raise ModelError("需要 1–200 个标量决策变量。")
    if not isinstance(constraints, list) or not 1 <= len(constraints) <= 1000:
        raise ModelError("需要 1–1000 条线性约束。")
    names = set()

    def provenance(item):
        if not isinstance(item, dict):
            raise ModelError("模型条目必须为对象。")
        source = item.get("source", "")
        assumption = item.get("assumption", "")
        if not isinstance(source, str) or not isinstance(assumption, str):
            raise ModelError("原文依据和假设必须为文本。")
        if source and source not in problem_text:
            raise ModelError("模型引用的依据未在需求原文中找到。")
        if not source and not assumption.strip():
            raise ModelError("每个模型条目需要原文依据或明确的待确认假设。")

    for var in variables:
        provenance(var)
        name = var.get("name", "")
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,39}", name) or name in names:
            raise ModelError("变量名必须唯一，使用英文字母、数字和下划线。")
        names.add(name)
        if var.get("domain") not in {"continuous", "integer", "binary"}:
            raise ModelError("变量类型必须为 continuous / integer / binary。")
        for bound in ("lower", "upper"):
            if var.get(bound) is not None:
                number(var[bound])
        if var.get("lower") is not None and var.get("upper") is not None and var["lower"] > var["upper"]:
            raise ModelError("变量下界不能超过上界。")
    if model["kind"] == "LP" and any(v["domain"] != "continuous" for v in variables):
        raise ModelError("含整数变量的模型必须标为 MILP。")

    def coefficients(item):
        values = item.get("coefficients")
        if not isinstance(values, dict) or not values or not set(values) <= names:
            raise ModelError("线性系数只能引用已定义的变量。")
        for value in values.values():
            number(value)

    objective = model.get("objective")
    provenance(objective)
    coefficients(objective)
    if objective.get("sense") not in {"max", "min"}:
        raise ModelError("目标方向必须为 max / min。")
    number(objective.get("constant", 0))
    ids = set()
    for constraint in constraints:
        provenance(constraint)
        coefficients(constraint)
        if constraint.get("relation") not in {"<=", ">=", "=="}:
            raise ModelError("约束关系必须为 <= / >= / ==。")
        number(constraint.get("rhs"))
        identifier = constraint.get("id")
        if not isinstance(identifier, str) or not identifier or identifier in ids:
            raise ModelError("约束编号必须唯一。")
        ids.add(identifier)
    for field in ("assumptions", "missing_inputs"):
        if not isinstance(model.get(field, []), list) or any(not isinstance(x, str) for x in model.get(field, [])):
            raise ModelError("假设和缺失输入需要使用文本列表。")
    return model


def expression(coefficients):
    return " + ".join(f"{value:g} × {name}" for name, value in coefficients.items())


def numerical_checks(model, solution, objective_value, tolerance=1e-5):
    """Recompute every constraint, domain and objective independently of solver logs."""
    names = {v["name"] for v in model["variables"]}
    if set(solution) != names:
        return {"numerical_feasibility": "not_checked", "checks": [], "reason": "求解器未返回完整决策量。"}
    try:
        values = {k: number(v) for k, v in solution.items()}
    except ModelError:
        return {"numerical_feasibility": "failed", "checks": [], "reason": "决策量含无效数值。"}
    checks = []

    def add(label, lhs, relation, rhs):
        signed = lhs - rhs
        violation = max(0, signed) if relation == "<=" else max(0, -signed) if relation == ">=" else abs(signed)
        limit = tolerance * max(1.0, abs(lhs), abs(rhs))
        checks.append({"name": label, "lhs": lhs, "relation": relation, "rhs": rhs,
                       "residual": signed, "violation": violation, "tolerance": limit,
                       "passed": violation <= limit})

    for c in model["constraints"]:
        lhs = sum(coef * values[name] for name, coef in c["coefficients"].items())
        add(c.get("label", c["id"]), lhs, c["relation"], c["rhs"])
    for var in model["variables"]:
        val = values[var["name"]]
        for bound, relation in (("lower", ">="), ("upper", "<=")):
            if var.get(bound) is not None:
                add(f"{var['name']} {bound}", val, relation, var[bound])
        if var["domain"] in {"integer", "binary"}:
            # Integer tolerance must not grow with the magnitude of the variable.
            delta = abs(val - round(val))
            checks.append({"name": f"{var['name']} 整数性", "lhs": val, "relation": "integer",
                           "rhs": round(val), "residual": delta, "violation": delta,
                           "tolerance": tolerance, "passed": delta <= tolerance})
        if var["domain"] == "binary":
            add(f"{var['name']} 二元下界", val, ">=", 0)
            add(f"{var['name']} 二元上界", val, "<=", 1)
    obj = model["objective"]
    computed = sum(coef * values[name] for name, coef in obj["coefficients"].items()) + obj.get("constant", 0)
    try:
        reported = number(objective_value)
    except ModelError:
        return {"numerical_feasibility": "failed", "checks": checks, "reason": "目标值缺失或无效。"}
    add("目标值重算", computed, "==", reported)
    return {"numerical_feasibility": "passed" if all(c["passed"] for c in checks) else "failed",
            "checks": checks, "recomputed_objective": computed, "tolerance": tolerance}

