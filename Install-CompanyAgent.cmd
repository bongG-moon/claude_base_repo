@echo off
setlocal EnableExtensions
call "%~dp0deploy\Install-CompanyAgent.cmd" %*
exit /b %ERRORLEVEL%
