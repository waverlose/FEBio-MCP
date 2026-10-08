@echo off
REM 手动启动 FEBio MCP Server（stdio）
setlocal
set "PYTHONPATH=%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
"%~dp0.venv\Scripts\python.exe" -m src.server %*
endlocal
