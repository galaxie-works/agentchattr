"""Live Claude Code session detection shared by the server and wrapper."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
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


def active_session_ids(claude_home: Path | None = None, process_is_running=None) -> set[str]:
    """Read Claude Code's live session registry, ignoring stale PID records."""
    registry_dir = (claude_home or (Path.home() / ".claude")) / "sessions"
    if not registry_dir.is_dir():
        return set()
    is_running = process_is_running or pid_is_running
    active: set[str] = set()
    for path in registry_dir.glob("*.json"):
        try:
            record = json.loads(path.read_text("utf-8"))
            session_id = record.get("sessionId")
            pid = int(record.get("pid", 0))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
        if isinstance(session_id, str) and session_id and is_running(pid):
            active.add(session_id)
    return active


def resume_target(extra_args: list[str]) -> str | None:
    """Return a Claude --resume target from pass-through wrapper arguments."""
    for index, arg in enumerate(extra_args):
        if arg == "--resume" and index + 1 < len(extra_args):
            return extra_args[index + 1]
        if arg.startswith("--resume="):
            return arg.partition("=")[2] or None
    return None
