@echo off
setlocal EnableExtensions
title Company Agent Setup

echo.
echo Company Agent easy setup
echo ========================
echo Choose all Claude sessions for your Windows account or one project.
echo Setup checks requirements, backs up existing customizations, and
echo installs the offline plugin. User/Project installation needs no UAC.
echo.
echo Model IDs, MCP details, Outlook email, and display name are NOT
echo requested during setup. Personal folders initialize automatically
echo on first launch. Outlook identity is configured separately only
echo when the Outlook MCP is first used.
echo.

set "COMPANY_AGENT_SETUP_NO_PAUSE="
for %%A in (%*) do (
    if /I "%%~A"=="-NonInteractive" set "COMPANY_AGENT_SETUP_NO_PAUSE=1"
)

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0Setup-CompanyAgent.ps1" %*
set "COMPANY_AGENT_SETUP_EXIT=%ERRORLEVEL%"

echo.
if "%COMPANY_AGENT_SETUP_EXIT%"=="0" (
    echo Setup finished. Close and reopen Claude Code to activate.
) else (
    echo Setup did not finish. Read the message above; your safety backup
    echo and any existing personal Company Agent data were kept.
)
echo.

if not defined COMPANY_AGENT_SETUP_NO_PAUSE if not "%COMPANY_AGENT_NO_PAUSE%"=="1" pause
exit /b %COMPANY_AGENT_SETUP_EXIT%
