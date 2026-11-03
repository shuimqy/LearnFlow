@echo off
setlocal
cd /d "%~dp0"
where node >nul 2>&1
if errorlevel 1 (
    echo Node.js was not found. Install Node.js 20.9 or later and try again.
    pause
    exit /b 1
)
node "%~dp0scripts\dev.mjs" start %*
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" pause
exit /b %RESULT%
