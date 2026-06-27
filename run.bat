@echo off
REM DeepSeek Web Agent Proxy - background launcher (non-blocking)
setlocal EnableExtensions

set "ROOT=D:\files\References\others\deepseek-web-agent"
set "PY=D:\files\References\others\deepseek-web-agent\.venv\Scripts\python.exe"
set "PORT=48391"

echo [run] killing old listeners on :%PORT%
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":%PORT% " ^| findstr LISTENING') do (
  echo [run]   kill PID %%a
  taskkill /F /PID %%a >nul 2>&1
)

cd /d "%ROOT%\proxy"
echo [run] cwd=%CD%

del /q "%ROOT%\proxy\stdout.log" 2>nul
del /q "%ROOT%\proxy\stderr.log" 2>nul

echo [run] launching on :%PORT%
start "DSProxy" /MIN cmd /c ""%PY%" "%ROOT%\proxy\main.py" 1> "%ROOT%\proxy\stdout.log" 2> "%ROOT%\proxy\stderr.log""

echo [run] launched. waiting 3s...
ping -n 4 127.0.0.1 >nul

echo.
echo [run] --- listener on :%PORT% ---
netstat -aon | findstr ":%PORT% " | findstr LISTENING
echo.
echo [run] --- stdout (last 30) ---
type "%ROOT%\proxy\stdout.log" | more
echo.
echo [run] --- stderr (last 20) ---
type "%ROOT%\proxy\stderr.log" | more

endlocal
