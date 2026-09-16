@echo off
setlocal
rem Use the same registered Python, scope and UTF-8 boundary as native hooks.
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -File "%~dp0..\scripts\Invoke-CompanyAgent.ps1" -Mode Cli %*
exit /b %ERRORLEVEL%
