@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 正在启动邀请制外网测试入口。首次需要下载官方隧道程序，请保持网络连接。
echo 就绪后入口保存在 runtime\share\入口信息.html，后台口令仅保存在本机。
".venv-workbench\Scripts\python.exe" run_experiment.py --share
if errorlevel 1 pause
