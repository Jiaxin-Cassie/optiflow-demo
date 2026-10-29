"""OptiFlow application entry point; filename retained for launcher compatibility."""
import argparse
import json
from pathlib import Path
import tempfile

from src.workbench.cli import add_arguments, dispatch


def smoke_test():
    """Check all business templates through the real local solver without API calls."""
    from src.workbench.cases import CASES
    from src.workbench.service import run_optimization_task, confirm_task
    from src.workbench.flow import confirm_business
    from src.workbench.store import TaskStore
    with tempfile.TemporaryDirectory(prefix="optiflow_smoke_") as directory:
        store = TaskStore(Path(directory) / "tasks.sqlite3")
        for case in CASES.values():
            task = run_optimization_task(case["text"], mode="case", case_id=case["id"], store=store, workflow_version=2)
            if task["status"] != "awaiting_confirmation":
                raise RuntimeError("Business template could not be modeled")
            confirm_business(task["task_id"], expected_version=1, store=store)
            task = confirm_task(task["task_id"], expected_version=1, store=store)
            if task["status"] != "completed":
                raise RuntimeError("Business template could not be solved")
            print(json.dumps({"case": case["id"], "status": task["solver"]["status"],
                              "objective": task["solver"]["objective_value"],
                              "numerical_feasibility": task["validation"]["numerical_feasibility"]}))


def main():
    parser = argparse.ArgumentParser(description="OptiFlow 智能优化决策工作台")
    add_arguments(parser)
    parser.add_argument("--smoke-test", action="store_true", help="Validate all built-in business cases locally")
    parser.add_argument("--package", metavar="ZIP_FILE", help="Build a clean portable source package without credentials or task data")
    parser.add_argument("--package-demo", metavar="ZIP_FILE", help="Build sanitized Streamlit Community Cloud sources for the public resume demo")
    parser.add_argument("--method", choices=["all"], help=argparse.SUPPRESS)
    parser.add_argument("--dry_run", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.package or args.package_demo:
        from src.workbench.package import build_package
        print(json.dumps(build_package(args.package_demo or args.package, profile="resume" if args.package_demo else "platform"), ensure_ascii=False, indent=2))
        return
    if args.smoke_test or (args.method == "all" and args.dry_run):
        smoke_test()
        return
    if args.method or args.dry_run:
        parser.error("Use --smoke-test for the local product check.")
    if dispatch(args):
        return
    args.workbench = True
    dispatch(args)


if __name__ == "__main__":
    main()
