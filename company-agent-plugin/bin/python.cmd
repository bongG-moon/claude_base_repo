@echo off
setlocal EnableExtensions
if not defined COMPANY_AGENT_PYTHON (
  echo COMPANY_AGENT_PYTHON is not set. Start this command from the Company Agent launcher. 1>&2
  exit /b 9009
)
"%COMPANY_AGENT_PYTHON%" %*
exit /b %ERRORLEVEL%
