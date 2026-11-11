@echo off
setlocal
cd /d "%~dp0"
set "STRATEGY_PYTHON=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if exist "%STRATEGY_PYTHON%" goto bundled
where py >nul 2>nul
if not errorlevel 1 goto launcher
where python >nul 2>nul
if not errorlevel 1 goto regular
echo Python 3.12 or later is required. See README.md.
pause
exit /b 1
:bundled
"%STRATEGY_PYTHON%" -m machine serve %*
goto finished
:launcher
py -3 -m machine serve %*
goto finished
:regular
python -m machine serve %*
:finished
if errorlevel 1 pause
endlocal
