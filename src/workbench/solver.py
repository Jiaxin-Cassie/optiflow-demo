"""Trusted interpreter for the reviewed linear model; generated Python is never run."""
import json
from time import perf_counter

from src.workbench.model import validate_model


def solve(model, problem_text):
    import cvxpy as cp
    import scipy

    validate_model(model, problem_text)
    if "SCIPY" not in cp.installed_solvers():
        raise RuntimeError("SCIPY / HiGHS 求解器不可用。")
    variables, constraints = {}, []
    for item in model["variables"]:
        var = cp.Variable(name=item["name"], integer=item["domain"] == "integer", boolean=item["domain"] == "binary")
        variables[item["name"]] = var
        if item.get("lower") is not None:
            constraints.append(var >= item["lower"])
        if item.get("upper") is not None:
            constraints.append(var <= item["upper"])
    for item in model["constraints"]:
        lhs = sum(coef * variables[name] for name, coef in item["coefficients"].items())
        constraints.append(lhs <= item["rhs"] if item["relation"] == "<=" else
                           lhs >= item["rhs"] if item["relation"] == ">=" else lhs == item["rhs"])
    obj = model["objective"]
    expr = sum(coef * variables[name] for name, coef in obj["coefficients"].items()) + obj.get("constant", 0)
    problem = cp.Problem(cp.Maximize(expr) if obj["sense"] == "max" else cp.Minimize(expr), constraints)
    started = perf_counter()
    problem.solve(solver="SCIPY", scipy_options={"method": "highs", "time_limit": 15.0})
    has_solution = problem.status in {"optimal", "optimal_inaccurate", "user_limit"} and all(v.value is not None for v in variables.values())
    record = {"modeling_tool": "CVXPY", "modeling_tool_version": cp.__version__, "backend": "SCIPY/HiGHS",
              "backend_version": scipy.__version__, "status": problem.status,
              "objective": float(problem.value) if has_solution else None,
              "variables": {k: float(v.value) for k, v in variables.items()} if has_solution else {},
              "selection_reason": "Reviewed LP/MILP interpreted by trusted CVXPY builder; HiGHS supports integer variables.",
              "elapsed_seconds": perf_counter() - started}
    return record


def emit_result(model, problem_text):
    print("SOLVER_RESULT:", json.dumps(solve(model, problem_text), ensure_ascii=True, allow_nan=False))

