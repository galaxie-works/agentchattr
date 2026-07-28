"""Provider capability checks and visible workspace-trust bootstrap sessions."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
import tomllib
import uuid
from dataclasses import dataclass
from pathlib import Path

from claude_sessions import reconcile_workspace_trust


DEFAULT_FULL_CONTROL_ARGS: dict[str, tuple[str, ...]] = {
    "claude": ("--dangerously-skip-permissions",),
    "codex": ("--dangerously-bypass-approvals-and-sandbox",),
    "gemini": ("--yolo",),
    "qwen": ("--yolo",),
}

DEFAULT_TRUST_KIND = {
    "claude": "claude",
    "codex": "codex",
    "gemini": "gemini",
    "qwen": "qwen",
}


def _normalized_workspace(path: str | Path) -> str:
    return str(Path(path).expanduser().resolve()).replace("\\", "/").rstrip("/").casefold()


def full_control_args(provider: str, agent_cfg: dict | None = None) -> tuple[str, ...] | None:
    """Return the verified/configured unattended flags, or None when unknown."""
    cfg = agent_cfg or {}
    configured = cfg.get("full_control_args")
    if isinstance(configured, list) and all(isinstance(item, str) and item for item in configured):
        return tuple(configured)
    return DEFAULT_FULL_CONTROL_ARGS.get(provider.lower())


def trust_kind(provider: str, agent_cfg: dict | None = None) -> str | None:
    cfg = agent_cfg or {}
    configured = cfg.get("workspace_trust")
    if configured == "none":
        return None
    if isinstance(configured, str) and configured:
        return configured.lower()
    return DEFAULT_TRUST_KIND.get(provider.lower())


def codex_workspace_is_trusted(cwd: str | Path, config_path: Path | None = None) -> bool:
    path = config_path or (Path.home() / ".codex" / "config.toml")
    try:
        payload = tomllib.loads(path.read_text("utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return False
    projects = payload.get("projects", {})
    if not isinstance(projects, dict):
        return False
    target = _normalized_workspace(cwd)
    return any(
        isinstance(project, str)
        and _normalized_workspace(project) == target
        and isinstance(cfg, dict)
        and cfg.get("trust_level") == "trusted"
        for project, cfg in projects.items()
    )


def json_folder_workspace_is_trusted(
    cwd: str | Path,
    config_path: Path,
) -> bool:
    """Resolve Gemini-style longest-prefix TRUST_FOLDER configuration."""
    try:
        payload = json.loads(config_path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict):
        return False
    target = _normalized_workspace(cwd)
    matches = []
    for folder, decision in payload.items():
        if not isinstance(folder, str):
            continue
        normalized = _normalized_workspace(folder)
        if target == normalized or target.startswith(f"{normalized}/"):
            matches.append((len(normalized), decision))
    if not matches:
        return False
    return max(matches, key=lambda item: item[0])[1] == "TRUST_FOLDER"


def workspace_is_trusted(kind: str | None, cwd: str | Path) -> bool:
    if kind is None:
        return True
    if kind == "claude":
        return reconcile_workspace_trust(cwd)
    if kind == "codex":
        return codex_workspace_is_trusted(cwd)
    if kind == "gemini":
        override = os.environ.get("GEMINI_CLI_TRUSTED_FOLDERS_PATH")
        path = Path(override) if override else Path.home() / ".gemini" / "trustedFolders.json"
        return json_folder_workspace_is_trusted(cwd, path)
    if kind == "qwen":
        return json_folder_workspace_is_trusted(cwd, Path.home() / ".qwen" / "trustedFolders.json")
    return False


@dataclass(frozen=True)
class ProviderPreflightTarget:
    provider: str
    label: str
    command: str
    cwd: Path
    full_control: tuple[str, ...] | None
    trust: str | None
    interactive: bool = True

    @property
    def resolved_command(self) -> str | None:
        return shutil.which(self.command)

    @property
    def trusted(self) -> bool:
        return workspace_is_trusted(self.trust, self.cwd)

    def public(self) -> dict:
        return {
            "provider": self.provider,
            "label": self.label,
            "command": self.command,
            "cwd": str(self.cwd),
            "full_control_args": list(self.full_control or ()),
            "installed": bool(self.resolved_command) if self.interactive else True,
            "full_control_supported": self.full_control is not None if self.interactive else True,
            "trust_required": self.trust is not None,
            "trusted": self.trusted,
        }


def preflight_blockers(targets: list[ProviderPreflightTarget]) -> list[str]:
    blockers = []
    for target in targets:
        if not target.interactive:
            continue
        if not target.cwd.is_dir():
            blockers.append(f"{target.label} working directory does not exist: {target.cwd}.")
        elif not target.resolved_command:
            blockers.append(f"{target.label} command '{target.command}' is not installed or not on PATH.")
        elif target.full_control is None:
            blockers.append(
                f"{target.label} has no verified full-control profile. "
                "Configure agents.<name>.full_control_args before launching it."
            )
    return blockers


def pending_trust(targets: list[ProviderPreflightTarget]) -> list[ProviderPreflightTarget]:
    return [
        target for target in targets
        if target.interactive and target.trust is not None and not target.trusted
    ]


def _powershell_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _visible_process(target: ProviderPreflightTarget) -> subprocess.Popen:
    command = target.resolved_command
    if not command or target.full_control is None:
        raise OSError(f"{target.label} cannot be started")
    if sys.platform == "win32":
        title = _powershell_quote(f"AgentChattr preflight · {target.label}")
        invocation = " ".join(_powershell_quote(item) for item in (command, *target.full_control))
        script = f"$Host.UI.RawUI.WindowTitle={title}; & {invocation}; exit $LASTEXITCODE"
        return subprocess.Popen(
            ["powershell", "-NoProfile", "-Command", script],
            cwd=target.cwd,
            creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
        )
    return subprocess.Popen(
        [command, *target.full_control],
        cwd=target.cwd,
        start_new_session=True,
    )


def _terminate_process_tree(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            timeout=10,
        )
        return
    process.terminate()


class ProviderPreflightSession:
    def __init__(self, targets: list[ProviderPreflightTarget], timeout_seconds: int = 600):
        self.id = uuid.uuid4().hex
        self.targets = targets
        self.timeout_seconds = timeout_seconds
        self.created_at = time.time()
        self.status = "starting"
        self.error = ""
        self._processes: dict[str, subprocess.Popen] = {}
        self._lock = threading.Lock()
        self._closed = threading.Event()

    def start(self) -> None:
        threading.Thread(target=self._run, daemon=True, name=f"provider-preflight-{self.id[:8]}").start()

    def _run(self) -> None:
        try:
            for target in self.targets:
                self._processes[target.provider] = _visible_process(target)
            with self._lock:
                self.status = "waiting"
            deadline = time.monotonic() + self.timeout_seconds
            while time.monotonic() < deadline:
                if self._closed.is_set():
                    return
                remaining = []
                for target in self.targets:
                    process = self._processes[target.provider]
                    if target.trusted:
                        _terminate_process_tree(process)
                    elif process.poll() is not None:
                        raise RuntimeError(
                            f"{target.label} closed before workspace trust was confirmed."
                        )
                    else:
                        remaining.append(target)
                if not remaining:
                    with self._lock:
                        self.status = "ready"
                    return
                time.sleep(0.4)
            raise TimeoutError("Workspace trust confirmation timed out.")
        except Exception as exc:
            with self._lock:
                self.status = "failed"
                self.error = str(exc)
            self.close()

    def close(self) -> None:
        self._closed.set()
        for process in list(self._processes.values()):
            try:
                _terminate_process_tree(process)
            except (OSError, subprocess.SubprocessError):
                pass

    def public(self) -> dict:
        with self._lock:
            return {
                "id": self.id,
                "status": self.status,
                "error": self.error,
                "targets": [target.public() for target in self.targets],
            }
