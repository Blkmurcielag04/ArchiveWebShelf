@echo off
cd /d "%~dp0"

set "PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
if exist "%PYTHON_EXE%" goto run

where py >nul 2>nul
if not errorlevel 1 (
  py -3 "%~dp0check_replaywebpage_update.py"
  goto done
)

where python >nul 2>nul
if not errorlevel 1 (
  python "%~dp0check_replaywebpage_update.py"
  goto done
)

echo Python was not found. Install Python or edit this launcher to point to python.exe.
goto done

:run
"%PYTHON_EXE%" "%~dp0check_replaywebpage_update.py"

:done
echo.
pause
