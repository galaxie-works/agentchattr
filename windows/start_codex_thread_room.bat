@echo off
REM AgentChattr room: server + current Codex thread relay + Claude wrapper.
REM Requires [thread_relays.codex-main] in config.local.toml.
setlocal
cd /d "%~dp0.."

if not exist ".venv\Scripts\python.exe" (
    echo.
    echo   Creating the local Python environment...
    python -m venv .venv || goto :error
    .venv\Scripts\pip install -q -r requirements.txt || goto :error
)

if not exist "config.local.toml" (
    echo.
    echo   Missing config.local.toml. Add [thread_relays.codex-main] before starting the room.
    goto :error
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

REM A thread relay is headless; do not launch a duplicate worker.
powershell -NoProfile -Command "if ((Get-CimInstance Win32_Process -Filter 'Name=''python.exe''').Where({$_.CommandLine -like '*thread_relay.py codex-main*'}).Count -gt 0) { exit 0 } else { exit 1 }" >nul 2>&1
if errorlevel 1 (
    start "AgentChattr Codex main relay" /min cmd /c ".venv\Scripts\python.exe -u thread_relay.py codex-main"
)

REM Prefer an explicit Claude session relay when configured through the Claude
REM identity pill. Fall back to the normal visible wrapper for older rooms.
.venv\Scripts\python.exe -c "from config_loader import load_config; import sys; sys.exit(0 if 'claude-main' in load_config().get('thread_relays', {}) else 1)" >nul 2>&1
if errorlevel 1 (
    where claude >nul 2>&1
    if errorlevel 1 (
        echo Claude CLI was not found on PATH; starting the Codex relay and room only.
    ) else (
        powershell -NoProfile -Command "if ((Get-CimInstance Win32_Process -Filter 'Name=''python.exe''').Where({$_.CommandLine -like '*wrapper.py claude-agentchattr*'}).Count -gt 0) { exit 0 } else { exit 1 }" >nul 2>&1
        if errorlevel 1 start "AgentChattr Claude" cmd /k ".venv\Scripts\python.exe wrapper.py claude-agentchattr"
    )
) else (
    powershell -NoProfile -Command "if ((Get-CimInstance Win32_Process -Filter 'Name=''python.exe''').Where({$_.CommandLine -like '*thread_relay.py claude-main*'}).Count -gt 0) { exit 0 } else { exit 1 }" >nul 2>&1
    if errorlevel 1 start "AgentChattr Claude main relay" /min cmd /c ".venv\Scripts\python.exe -u thread_relay.py claude-main"
)

start "" "http://127.0.0.1:8300"
exit /b 0

:error
echo.
echo   AgentChattr room did not start. See the message above.
pause
exit /b 1
