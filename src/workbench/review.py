"""Source-to-model alignment, actual model changes and actionable decision summaries."""
from src.workbench.explanations import model_review_data, decision_summary, compare_versions, fmt, finite


def _entries(model):
    if not isinstance(model, dict):
        return {}
    view = model_review_data(model)
    entries = {}
    objective = model.get("objective") or {}
    if objective:
        entries["objective"] = {"kind":"目标", "label":objective.get("label", "优化目标"), "source":objective.get("source", ""),
                                "meaning":view["goal"], "formula":view["objective_formula"], "value":objective}
    for variable in view["decisions"]:
        name = variable["name"]
        raw = next(v for v in model.get("variables", []) if v.get("name")==name)
        entries["variable:"+name] = {"kind":"决策数量", "label":variable["label"], "source":raw.get("source", ""),
            "meaning":f"决定{variable['label']}；单位为{variable['unit']}，{variable['domain']}。数量下限 {variable['lower']}，上限 {variable['upper']}。",
            "formula":name, "value":raw}
    labels = {v["name"]: v.get("label",v["name"]) for v in model.get("variables", [])}
    words = {"<=":"不能超过", ">=":"至少达到", "==":"必须等于"}
    for index, constraint in enumerate(model.get("constraints", [])):
        terms = " + ".join(f"{fmt(n)} × {labels.get(k,k)}" for k,n in constraint.get("coefficients", {}).items())
        meaning = f"{terms}，{words.get(constraint.get('relation'),'关系待核对')} {fmt(constraint.get('rhs'))}。"
        unit = constraint.get("unit")
        if unit:
            meaning += "本条规则单位："+str(unit)+"。"
        entries["constraint:"+str(constraint.get("id",index))] = {"kind":"业务规则", "label":constraint.get("label", "业务限制"),
            "source":constraint.get("source", ""), "meaning":meaning,
            "formula":" + ".join(f"{fmt(n)} × {k}" for k,n in constraint.get("coefficients",{}).items())+f" {constraint.get('relation','?')} {fmt(constraint.get('rhs'))}",
            "value":constraint}
    return entries


def model_alignment(task):
    previous = next((v for v in reversed(task.get("versions", [])) if v.get("model")), None)
    old = _entries(previous["model"]) if previous else {}
    current = _entries(task.get("model"))
    rows = []
    for key, entry in current.items():
        status = "初始规则" if not previous else "新增" if key not in old else "保持不变" if entry["value"]==old[key]["value"] else "已修改"
        rows.append({"key":key, **entry, "status":status, "before":old.get(key)})
        if key.startswith("constraint:"):
            rule=entry["value"]
            coefficients=rule.get("coefficients",{})
            if len(coefficients)==1 and next(iter(coefficients.values()))==1:
                name=next(iter(coefficients))
                variable=next((v for v in task["model"].get("variables",[]) if v["name"]==name),{})
                relation={"<=":"不能超过",">=":"至少达到","==":"必须等于"}.get(rule.get("relation"),"关系待核对")
                rows[-1]["meaning"]=f"{variable.get('label',name)}{relation} {fmt(rule.get('rhs'))} {variable.get('unit','')}。"
            elif task.get("mode")=="case" and task.get("case_id")=="production" and rule.get("id") in {"labor","machine"}:
                resource="人工" if rule["id"]=="labor" else "机器"
                rows[-1]["meaning"]=f"每件 A 使用 {fmt(coefficients.get('A',0))} 小时{resource}，每件 B 使用 {fmt(coefficients.get('B',0))} 小时{resource}；合计不能超过 {fmt(rule.get('rhs'))} 小时。"
    for key,entry in old.items():
        if key not in current:
            rows.append({"key":key, **entry, "status":"已移除", "before":entry})
    counts = {label:sum(r["status"]==label for r in rows) for label in ["新增", "已修改", "已移除", "保持不变"]}
    if previous:
        rows.sort(key=lambda r:{"新增":0,"已修改":1,"已移除":2,"保持不变":3}.get(r["status"],4))
    return {"rows":rows, "previous_version":previous["model_version"] if previous else None,
            "current_version":task["model_version"], "counts":counts, "revision_note":task.get("revision_note") or ""}


def decision_brief(task):
    summary = decision_summary(task)
    result = {**summary,"change_explanation":None,"resource_rows":[],"actions":[],"decision_rows":[]}
    if not summary["eligible"]:
        return result
    variables = task["model"]["variables"]
    solution = task["solver"]["solution"]
    result["decision_rows"] = [{"label":v.get("label",v["name"]),"value":solution[v["name"]],"unit":v.get("unit","")} for v in variables]
    result["actions"] = ["按上述数量安排本次计划，并在执行前确认资源与利润数据仍然适用。",
                         "如有新的数量限制或业务要求，先补充需求、重新确认，再使用更新后的方案。"]
    if task.get("case_id") != "production":
        result["actions"][0] = "按上述决策量制定执行计划，实施前确认输入数据和假设仍然适用。"
    old = next((v for v in task.get("versions",[]) if v.get("model_version")==1),None)
    if old:
        difference = compare_versions(old,task)
        if difference["comparable"]:
            unchanged = all(r["delta"]==0 for r in difference["variables"])
            if difference["delta"]==0 and unchanged:
                result["change_explanation"] = "新增要求已经进入模型。当前产量与目标值均与初始方案相同，原方案仍满足更新后的限制，因此可沿用原方案，无需为了增加一条规则而强行调整数量。"
            elif difference["delta"]==0:
                result["change_explanation"] = "目标值保持不变，但决策数量组合有变化。请按当前版本的数量执行，并核对版本对比。"
            else:
                result["change_explanation"] = difference["summary"]
    for constraint in task["model"].get("constraints",[]):
        coefficients=constraint.get("coefficients",{})
        if constraint.get("relation")!="<=" or not finite(constraint.get("rhs")):
            continue
        lhs=sum(coefficient*solution[name] for name,coefficient in coefficients.items())
        result["resource_rows"].append({"规则":constraint.get("label",constraint.get("id","业务限制")),
                                        "本方案用量":lhs,"上限":constraint["rhs"],"剩余空间":constraint["rhs"]-lhs})
    return result
