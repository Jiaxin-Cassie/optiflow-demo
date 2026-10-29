"""Local workers persist progress to SQLite without touching Streamlit state."""
import os
import subprocess
import sys

from src.workbench.store import ROOT


def launch(task_id, action, store):
    if action not in {"prepare", "solve"}:
        raise ValueError("未知工作任务。")
    log_dir = store.path.parent / "worker_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    with (log_dir / f"{task_id}.log").open("a", encoding="utf-8") as log:
        worker = subprocess.Popen([sys.executable, str(ROOT / "run_experiment.py"), "--workbench-worker", task_id,
                                   "--workbench-action", action, "--workbench-db", str(store.path.resolve())],
                                  cwd=ROOT, stdout=log, stderr=log, creationflags=flags)
    return worker.pid

