@echo off
setlocal
if defined COMPANY_AGENT_PYTHON (
  "%COMPANY_AGENT_PYTHON%" "%~dp0..\scripts\harness_cli.py" %*
) else (
  python "%~dp0..\scripts\harness_cli.py" %*
)
exit /b %ERRORLEVEL%
