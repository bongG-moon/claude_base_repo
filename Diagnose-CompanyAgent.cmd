@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy\Diagnose-CompanyAgent.ps1" %*
set "COMPANY_AGENT_DIAGNOSTIC_EXIT=%ERRORLEVEL%"
echo.
if not "%COMPANY_AGENT_NO_PAUSE%"=="1" pause
exit /b %COMPANY_AGENT_DIAGNOSTIC_EXIT%
