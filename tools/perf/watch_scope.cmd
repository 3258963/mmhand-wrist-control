@echo off
setlocal
rem 一条命令：拉起上位机（带内部遥测）+ 实时监视，Ctrl+C 结束并自动关闭。
rem 需要监视已在运行的实例时，去掉 --launch 并手动设 MMHAND_TELEMETRY。
set "HERE=%~dp0"
set "ROOT=%HERE%..\.."
set "PY=%ROOT%\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
pushd "%ROOT%" || exit /b 1
"%PY%" "tools\perf\watch_scope.py" --launch %*
set "rc=%errorlevel%"
popd
exit /b %rc%
