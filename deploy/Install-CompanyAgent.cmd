@echo off
setlocal EnableExtensions
title Company Agent Setup

echo.
echo Company Agent easy setup
echo ========================
echo Choose all Claude sessions for your Windows account or one project.
echo Setup checks requirements, backs up existing customizations, and
echo installs the offline plugin. User/Project installation needs no UAC.
echo Setup verifies your current Windows account and existing Claude paths.
echo Elevated same-user sessions are supported; other accounts are blocked.
echo Existing Company Agent: shows current-to-new version and offers Update.
echo Update backs up and preserves personal data, custom rules, and hooks.
echo Same version: reapply/repair. Other harness: Keep or Backup and replace.
echo If Skill names overlap, choose current preferences or incoming Skills.
echo You can change project Skill preferences later in /company-agent:skills.
echo.
echo Company-approved Python 3.11+ and Claude Code must already be installed.
echo Setup finds Python automatically through python or py. If not found,
echo enter the approved python.exe path. Setup does not install or download
echo Python or pip, and does not change your PC's PATH settings.
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
    echo Setup finished. Success: installed / updated / reapplied.
    echo kept or input-required means no installation/update was performed.
    echo After success, close and reopen Claude Code to activate.
) else (
    echo Setup did not finish. Read the error above before retrying.
    echo A preflight failure may occur before any backup is created.
    echo If a backup was created, its location is shown above. Do not delete
    echo existing settings or personal data to resolve an installation error.
)
echo.

if not defined COMPANY_AGENT_SETUP_NO_PAUSE if not "%COMPANY_AGENT_NO_PAUSE%"=="1" pause
exit /b %COMPANY_AGENT_SETUP_EXIT%
