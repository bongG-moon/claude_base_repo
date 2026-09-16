@echo off
setlocal EnableExtensions
title Company Agent Setup

rem Keep CMD ASCII-only. Korean messages come from the UTF-8 BOM PS1.

set "COMPANY_AGENT_SETUP_NO_PAUSE="
for %%A in (%*) do (
    if /I "%%~A"=="-NonInteractive" set "COMPANY_AGENT_SETUP_NO_PAUSE=1"
)

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0Setup-CompanyAgent.ps1" -FriendlyOutput %*
set "COMPANY_AGENT_SETUP_EXIT=%ERRORLEVEL%"

if not defined COMPANY_AGENT_SETUP_NO_PAUSE if not "%COMPANY_AGENT_NO_PAUSE%"=="1" pause >nul
exit /b %COMPANY_AGENT_SETUP_EXIT%
