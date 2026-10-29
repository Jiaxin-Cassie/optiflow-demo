@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist ".venv-workbench\Scripts\python.exe" (
    ".venv-workbench\Scripts\python.exe" run_experiment.py --workbench
) else (
    python run_experiment.py --workbench
)
if errorlevel 1 pause

