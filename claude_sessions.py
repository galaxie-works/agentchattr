"""Live Claude Code session detection shared by the server and wrapper."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path


def pid_is_running(pid: int) -> bool:
    """Return whether a local PID still exists without ever signalling it."""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=3,
            )
            return bool(re.search(rf'^"[^"]+","{pid}"', result.stdout, re.MULTILINE))
        except (OSError, subprocess.SubprocessError):
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def active_sessions(claude_home: Path | None = None, process_is_running=None) -> dict[str, set[int]]:
    """Read Claude Code's live session registry, ignoring stale PID records."""
    registry_dir = (claude_home or (Path.home() / ".claude")) / "sessions"
    if not registry_dir.is_dir():
        return {}
    is_running = process_is_running or pid_is_running
    active: dict[str, set[int]] = {}
    for path in registry_dir.glob("*.json"):
        try:
            record = json.loads(path.read_text("utf-8"))
            session_id = record.get("sessionId")
            pid = int(record.get("pid", 0))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
        if isinstance(session_id, str) and session_id and is_running(pid):
            active.setdefault(session_id, set()).add(pid)
    return active


def active_session_ids(claude_home: Path | None = None, process_is_running=None) -> set[str]:
    """Compatibility helper for callers that only need session identifiers."""
    return set(active_sessions(claude_home, process_is_running))


def _windows_process_info(pid: int) -> tuple[int, str] | None:
    """Return parent PID and command line for one process without displaying a console."""
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", f"$p=Get-CimInstance Win32_Process -Filter 'ProcessId={pid}'; if ($p) {{ \"$($p.ParentProcessId)`t$($p.CommandLine)\" }}"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=3,
        )
        line = result.stdout.strip()
        parent, separator, command_line = line.partition("\t")
        return (int(parent), command_line) if separator and parent.isdigit() else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def _termination_root(pid: int, process_info) -> int:
    """Stop an owning AgentChattr wrapper, otherwise only the Claude CLI PID."""
    candidate = pid
    seen: set[int] = set()
    while candidate not in seen:
        seen.add(candidate)
        info = process_info(candidate)
        if not info:
            break
        parent_pid, command_line = info
        if "wrapper.py" in command_line.lower() and "claude" in command_line.lower():
            return candidate
        if parent_pid <= 0:
            break
        candidate = parent_pid
    return pid


def terminate_sessions(session_ids: set[str], claude_home: Path | None = None) -> set[str]:
    """Terminate only approved live Claude sessions and wait briefly for exit.

    On Windows an AgentChattr wrapper is terminated at its root so its normal
    restart loop cannot recreate the same CLI session after the child exits.
    """
    matching = {sid: pids for sid, pids in active_sessions(claude_home).items() if sid in session_ids}
    pids = {pid for pids in matching.values() for pid in pids}
    if not pids:
        return set()

    if sys.platform == "win32":
        roots = {_termination_root(pid, _windows_process_info) for pid in pids}
        for pid in roots:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=8,
            )
    else:
        for pid in pids:
            try:
                os.kill(pid, 15)
            except OSError:
                pass

    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        remaining = set(active_sessions(claude_home)) & session_ids
        if not remaining:
            return set()
        time.sleep(0.15)
    return set(active_sessions(claude_home)) & session_ids


def resume_target(extra_args: list[str]) -> str | None:
    """Return a Claude --resume target from pass-through wrapper arguments."""
    for index, arg in enumerate(extra_args):
        if arg == "--resume" and index + 1 < len(extra_args):
            return extra_args[index + 1]
        if arg.startswith("--resume="):
            return arg.partition("=")[2] or None
    return None
