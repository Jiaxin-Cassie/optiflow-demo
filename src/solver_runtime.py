"""Shared environment facts and backend-aware result parsing; no model-selection policy."""
import importlib.util
import importlib.metadata
import json
import math
import re
from functools import lru_cache


@lru_cache(maxsize=1)
def solver_environment():
    # Describe only the product's supported interpreter. Inspecting unrelated
    # research installations can start license probes and create unwanted logs.
    if any(importlib.util.find_spec(name) is None for name in ("cvxpy", "scipy")):
        return {}
    return {"cvxpy": {"package_version": importlib.metadata.version("cvxpy"),
                      "backends": ["SCIPY"], "solver": "HiGHS", "supports": ["LP", "MILP"]}}


def normalize_status(status, modeling_tool="", backend=""):
    raw = str(status).strip().lower().replace(" ", "_")
    tool = str(modeling_tool).lower()
    solver = str(backend).lower()
    if raw.lstrip("-").isdigit():
        if "gurobi" in tool or "gurobi" in solver:
            return {"1": "Loaded", "2": "Optimal", "3": "Infeasible",
                    "4": "InfeasibleOrUnbounded", "5": "Unbounded", "9": "Timeout",
                    "12": "NumericalError", "13": "Suboptimal", "18": "LocallyOptimal",
                    "19": "LocallyInfeasible"}.get(raw, "Stopped")
        # PuLP's modeling-layer status must not be confused with native backend codes.
        if tool == "pulp" or (not tool and solver in {"pulp", "pulp/cbc"}):
            return {"1": "Optimal", "0": "NotSolved", "-1": "Infeasible",
                    "-2": "Unbounded", "-3": "Undefined"}.get(raw, "Unknown")
        return "Unknown"
    names = {
        "optimal": "Optimal", "optimal_solution_found": "Optimal",
        "optimal_inaccurate": "OptimalInaccurate", "locally_optimal": "LocallyOptimal",
        "local_optimal": "LocallyOptimal", "infeasible": "Infeasible",
        "infeasible_inaccurate": "InfeasibleInaccurate", "unbounded": "Unbounded",
        "unbounded_inaccurate": "UnboundedInaccurate", "inf_or_unbd": "InfeasibleOrUnbounded",
        "infeasible_or_unbounded": "InfeasibleOrUnbounded", "time_limit": "Timeout",
        "timelimit": "Timeout", "timeout": "Timeout", "not_solved": "NotSolved",
        "suboptimal": "Suboptimal", "loaded": "Loaded", "user_limit": "UserLimit",
    }
    return names.get(raw, "Unknown")


def finite_number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def parse_solver_record(stdout):
    """Only the final explicitly labelled record is authoritative, never arbitrary log prose."""
    lines = [s.strip()[len("SOLVER_RESULT:"):].strip() for s in stdout.splitlines()
             if s.strip().startswith("SOLVER_RESULT:")]
    if not lines:
        return None
    try:
        record = json.loads(lines[-1])
        required = {"modeling_tool", "backend", "backend_version", "status", "objective", "variables", "selection_reason"}
        if not isinstance(record, dict) or not required <= record.keys():
            raise ValueError()
        if not all(isinstance(record[k], str) and record[k].strip()
                   for k in ("modeling_tool", "backend", "backend_version", "selection_reason")):
            raise ValueError()
        if not isinstance(record["variables"], dict) or not isinstance(record["status"], (str, int)):
            raise ValueError()
        if record["objective"] is not None and finite_number(record["objective"]) is None:
            raise ValueError()
        if any(finite_number(v) is None for v in record["variables"].values()):
            raise ValueError()
        normalized = normalize_status(record["status"], record["modeling_tool"], record["backend"])
        # PuLP/CBC can set status=1 after a time limit with only an incumbent.
        # Generated programs may serialize model.sol_status either as its integer code
        # or through pulp.LpSolution[model.sol_status]. Both are accepted explicitly.
        if record["modeling_tool"].lower() == "pulp" and normalized == "Optimal":
            solution_status = str(record.get("solution_status", "")).strip().casefold()
            if solution_status in {"2", "solution found", "integer feasible", "feasible"}:
                normalized = "FeasibleNotProvenOptimal"
            elif solution_status not in {"1", "optimal", "optimal solution found"}:
                normalized = "OptimalityUnverified"
        return {**record, "objective": finite_number(record["objective"]),
                "normalized_status": normalized,
                "result_protocol": "solver_result_v1"}
    except (ValueError, TypeError):
        return {"status": "InvalidResult", "normalized_status": "InvalidResult",
                "objective": None, "variables": {}, "result_protocol": "invalid_solver_result_v1"}


def legacy_backend(stdout):
    hits = re.findall(r"(?im)^\s*Solver Backend:\s*([^\r\n]+)", stdout)
    return hits[-1].strip() if hits else "unknown"
