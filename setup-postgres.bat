@echo off
setlocal
cd /d "%~dp0"
uv run --locked --all-packages python -m app.cli.database setup
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" pause
exit /b %RESULT%
