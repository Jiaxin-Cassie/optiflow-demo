"""Deterministic business views of reviewed model data; no model-service calls."""
import hashlib
import json
import math


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def fmt(value):
    if not finite(value):
        return "未提供"
    return f"{0 if abs(value) < 1e-9 else value:,.6f}".rstrip("0").rstrip(".")


def _items(value):
    return [x for x in value if isinstance(x, dict)] if isinstance(value, list) else []


def _text(value, fallback="未提供"):
    return value.strip() if isinstance(value, str) and value.strip() else fallback


def _formula(coefficients):
    if not isinstance(coefficients, dict) or not coefficients or not all(finite(v) for v in coefficients.values()):
        return "表达式不完整，请检查模型。"
    return " + ".join(f"({fmt(v)}) × {k}" for k, v in coefficients.items())


def model_review_data(model):
    model = model if isinstance(model, dict) else {}
    variables = [v for v in _items(model.get("variables")) if isinstance(v.get("name"), str)]
    constraints = _items(model.get("constraints"))
    objective = model.get("objective") if isinstance(model.get("objective"), dict) else {}
    labels = {v.get("name"): _text(v.get("label"), str(v.get("name", "未命名决策量"))) for v in variables}
    decisions, rules = [], []
    assumptions = [s for s in model.get("assumptions", []) if isinstance(s, str) and s.strip()] if isinstance(model.get("assumptions"), list) else []
    missing = [s for s in model.get("missing_inputs", []) if isinstance(s, str) and s.strip()] if isinstance(model.get("missing_inputs"), list) else []
    for item in [*variables, objective, *constraints]:
        if isinstance(item.get("assumption"), str) and item["assumption"].strip():
            assumptions.append(item["assumption"])
    for var in variables:
        name = var.get("name", "未命名")
        domain = {"integer": "整数（按完整数量安排）", "continuous": "可取小数的数量", "binary": "是否选择（0 表示不选，1 表示选择）"}.get(var.get("domain"), "类型未提供，需核实")
        if var.get("domain") == "integer" and finite(var.get("lower")) and var["lower"] >= 0:
            domain = "非负整数（按完整数量安排）"
        decisions.append({"name": name, "label": labels.get(name, "未命名决策量"), "unit": _text(var.get("unit"), "未标注"),
                          "domain": domain, "lower": fmt(var["lower"]) if var.get("lower") is not None else "未设置",
                          "upper": fmt(var["upper"]) if var.get("upper") is not None else "未设置", "source": var.get("source", ""),
                          "assumption": var.get("assumption", ""), "technical_domain": var.get("domain", "未提供")})
        for bound, relation, phrase in (("lower", ">=", "至少为"), ("upper", "<=", "最多为")):
            if finite(var.get(bound)):
                rules.append({"label": f"{labels[name]} · 数量{'下限' if bound == 'lower' else '上限'}",
                              "description": f"{labels[name]}{phrase} {fmt(var[bound])} {_text(var.get('unit'), '')}。",
                              "formula": f"{name} {relation} {fmt(var[bound])}", "source": var.get("source", ""),
                              "assumption": var.get("assumption", ""), "kind": "bound"})
        if var.get("domain") == "binary":
            rules.append({"label": f"{labels[name]} · 是否选择", "description": "只能取 0 或 1，不能安排部分选择。",
                          "formula": f"{name} ∈ {{0, 1}}", "source": var.get("source", ""), "kind": "domain"})
    relation_words = {"<=": "不能超过", ">=": "至少达到", "==": "必须等于"}
    for constraint in constraints:
        coefficients = constraint.get("coefficients")
        terms = []
        if isinstance(coefficients, dict):
            terms = [f"{labels.get(name, str(name))} × ({fmt(coef)})" for name, coef in coefficients.items()]
        # Coefficient units are not part of the current contract: never invent resource units.
        description = "该规则限制以下决策量的加权总和：" + "；".join(terms) if terms else "该规则的系数不完整，需核实。"
        relation = constraint.get("relation")
        description += f"。加权结果{relation_words.get(relation, '关系未明确，边界为')} {fmt(constraint.get('rhs'))}"
        description += f" {_text(constraint.get('unit'), '')}" if constraint.get("unit") else "（按该规则的数值口径）"
        rules.append({"label": _text(constraint.get("label"), str(constraint.get("id", "未命名规则"))),
                      "description": description + "。", "formula": f"{_formula(coefficients)} {relation or '?'} {fmt(constraint.get('rhs'))}",
                      "source": constraint.get("source", ""), "assumption": constraint.get("assumption", ""), "kind": "constraint"})
    direction = {"max": "尽可能提高", "min": "尽可能降低"}.get(objective.get("sense"), "优化")
    goal = f"在满足当前模型已列出的业务规则与数量边界时，决定各项数量，{direction}“{_text(objective.get('label'), '目标值')}”。"
    return {"goal": goal, "objective_formula": f"{objective.get('sense', '?')} {_formula(objective.get('coefficients'))} + {fmt(objective.get('constant', 0))}",
            "objective_label": _text(objective.get("label"), "目标值"), "objective": objective,
            "decisions": decisions, "rules": rules, "assumptions": list(dict.fromkeys(assumptions)), "missing_inputs": missing,
            "variable_count": len(variables), "constraint_count": len(constraints)}


def valid_result(version):
    from src.workbench.flow import business_confirmed
    if version.get("workflow_version", 1) >= 2 and not business_confirmed(version):
        return False
    model = version.get("model") or {}
    if not isinstance(model, dict):
        return False
    solver, validation = version.get("solver") or {}, version.get("validation") or {}
    variables = _items(model.get("variables"))
    objective = model.get("objective")
    if not isinstance(objective, dict) or objective.get("sense") not in {"max", "min"} or not isinstance(objective.get("coefficients"), dict):
        return False
    solution = solver.get("solution")
    if any(not isinstance(v.get("name"), str) for v in variables):
        return False
    if (solver.get("status") != "Optimal" or solver.get("code_executable") is not True
            or validation.get("numerical_feasibility") != "passed" or not finite(solver.get("objective_value"))
            or not variables or not isinstance(solution, dict) or len({v.get("name") for v in variables}) != len(variables)):
        return False
    if set(solution) != {v.get("name") for v in variables} or not all(finite(n) for n in solution.values()):
        return False
    review = version.get("human_review") or {}
    if review.get("status") != "confirmed" or review.get("version") != version.get("model_version"):
        return False
    try:
        digest = hashlib.sha256(json.dumps(model, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()).hexdigest()
    except (TypeError, ValueError):
        return False
    return review.get("model_hash") == digest and version.get("model_hash") == digest


def decision_summary(task):
    model, solver = task.get("model") or {}, task.get("solver") or {}
    status = solver.get("status", "未求解")
    limitations = "数值检查通过表示结果满足当前数学模型，不代表原始业务需求已经得到独立验证。"
    allowed = valid_result(task) and task.get("status", "completed") == "completed"
    if not allowed:
        next_step = {"Infeasible": "检查最低需求与可用资源是否冲突，再补充或调整需求。", "Unbounded": "检查是否缺少数量上限或资源约束。",
                     "Timeout": "缩小问题规模或检查求解预算后重试。", "Unknown": "检查执行记录与模型，当前无法确定有效方案。"}.get(status, "请完成模型确认和求解，并核对数值检查与完整决策量。")
        return {"eligible": False, "recommendation": None, "objective_summary": None, "feasibility_summary": None,
                "status": status, "next_step": next_step, "limitations": limitations}
    view = model_review_data(model)
    recommendation = "建议安排：" + "；".join(f"{v['label']} {fmt(solver['solution'][v['name']])} {v['unit']}" for v in view["decisions"]) + "。"
    objective = model["objective"]
    return {"eligible": True, "recommendation": recommendation,
            "objective_summary": f"本方案以{'最大化' if objective.get('sense') == 'max' else '最小化'}{view['objective_label']}为目标，模型计算结果为 {fmt(solver['objective_value'])} {_text(objective.get('unit'), '（单位未标注）')}。",
            "feasibility_summary": f"结果通过当前模型中 {view['constraint_count']} 条显式约束及变量边界、整数性和目标值重算检查。",
            "limitations": limitations}


def _semantics(model):
    return {v["name"]: (v.get("label"), v.get("unit"), v.get("domain")) for v in _items(model.get("variables")) if isinstance(v.get("name"), str)}


def compare_versions(before, after):
    """Conservative comparisons; a changed feasible region alone does not block them."""
    reasons = []
    a, b = before.get("model") or {}, after.get("model") or {}
    oa, ob = a.get("objective") or {}, b.get("objective") or {}
    if not valid_result(before) or not valid_result(after):
        reasons.append("两个版本都需要完整、最优且数值通过的已确认结果")
    for key, label in (("sense", "优化方向"), ("unit", "目标单位"), ("label", "目标业务标签")):
        if not oa.get(key) or not ob.get(key) or oa.get(key) != ob.get(key):
            reasons.append(label + "变化或未明确")
    if oa.get("coefficients") != ob.get("coefficients") or oa.get("constant", 0) != ob.get("constant", 0):
        reasons.append("目标系数或常数项发生变化")
    if _semantics(a) != _semantics(b) or any(not label or not unit for label, unit, _ in _semantics(a).values()):
        reasons.append("变量数量、名称、含义、单位或类型变化或未明确")
    if a.get("assumptions", []) != b.get("assumptions", []) or a.get("missing_inputs") or b.get("missing_inputs"):
        reasons.append("假设或缺失信息影响可比性")
    variable_assumptions = lambda m: {v["name"]: v.get("assumption", "") for v in _items(m.get("variables")) if isinstance(v.get("name"), str)}
    if variable_assumptions(a) != variable_assumptions(b) or oa.get("assumption", "") != ob.get("assumption", ""):
        reasons.append("决策对象或目标假设发生变化")
    rows = []
    sa, sb = (before.get("solver") or {}).get("solution") or {}, (after.get("solver") or {}).get("solution") or {}
    for name in sorted(set(sa) | set(sb)):
        same = name in _semantics(a) and _semantics(a).get(name) == _semantics(b).get(name)
        delta = sb[name] - sa[name] if same and finite(sa.get(name)) and finite(sb.get(name)) else None
        rows.append({"variable": name, "before": sa.get(name), "after": sb.get(name), "delta": 0.0 if delta is not None and abs(delta) < 1e-8 else delta,
                     "semantics_match": same, "label": (_semantics(b).get(name) or _semantics(a).get(name) or (name,))[0]})
    changes = after.get("revision_note") or (after.get("effective_text") if after.get("effective_text") != before.get("effective_text") else "需求文字未变化")
    result = {"comparable": not reasons, "reasons": reasons, "variables": rows, "change_note": changes,
              "before_value": (before.get("solver") or {}).get("objective_value"), "after_value": (after.get("solver") or {}).get("objective_value"),
              "delta": None, "relative_percent": None, "improvement": None}
    if reasons:
        result["summary"] = "目标值不宜直接比较：" + "；".join(reasons) + "。"
        return result
    old, new = result["before_value"], result["after_value"]
    delta = new - old
    if math.isclose(old, new, rel_tol=1e-12, abs_tol=1e-8):
        delta = 0.0
    result.update(delta=delta, relative_percent=100 * delta / abs(old) if old != 0 else None,
                  improvement="不变" if delta == 0 else "改善" if (delta > 0) == (ob["sense"] == "max") else "下降")
    result["summary"] = (f"v{before['model_version']} → v{after['model_version']}：{ob['label']}"
                         f"{'保持不变' if delta == 0 else ('增加' if delta > 0 else '减少') + ' ' + fmt(abs(delta)) + ' ' + ob['unit']}。"
                         f"按{'最大化' if ob['sense'] == 'max' else '最小化'}目标衡量为“{result['improvement']}”。"
                         "这是对应模型版本的结果差异，不能据此断言某项修改是唯一原因。")
    return result
