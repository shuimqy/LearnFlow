@echo off
call "%~dp0start.bat" --multiuser %*
exit /b %ERRORLEVEL%
