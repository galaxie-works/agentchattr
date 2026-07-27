@echo off
REM AgentChattr room bootstrap. The first-run wizard chooses and starts
REM wrappers or explicit relays after the user configures the room.
setlocal
cd /d "%~dp0.."

if not exist ".venv\Scripts\python.exe" (
    echo.
    echo   Creating the local Python environment...
    python -m venv .venv || goto :error
    .venv\Scripts\pip install -q -r requirements.txt || goto :error
)

REM Start the local-only web/MCP server once.
netstat -ano | findstr :8300 | findstr LISTENING >nul 2>&1
if errorlevel 1 (
    start "AgentChattr server" /min cmd /c ".venv\Scripts\python.exe -u run.py"
)

:wait_server
netstat -ano | findstr :8300 | findstr LISTENING >nul 2>&1
if errorlevel 1 (
    timeout /t 1 /nobreak >nul
    goto :wait_server
)

start "" "http://127.0.0.1:8300"
exit /b 0

:error
echo.
echo   AgentChattr room did not start. See the message above.
pause
exit /b 1
