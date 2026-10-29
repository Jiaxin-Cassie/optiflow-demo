@echo off
chcp 65001 >nul
cd /d "%~dp0"
".venv-workbench\Scripts\python.exe" run_experiment.py --share-stop
pause
