"""Configuration for relays that address one persisted Codex thread.

Thread relays are intentionally explicit.  They never scan local session
storage, infer deep links, or accept a thread ID from a room message.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import uuid


_HANDLE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,30}$")


@dataclass(frozen=True)
class ThreadRelay:
    name: str
    thread_id: str
    cwd: Path
    command: str
    label: str
    color: str
    timeout_seconds: int


class ThreadRelays:
    """Validated local thread-relay definitions."""

    def __init__(self, config: dict | None, agent_names: set[str], root: Path):
        self._relays: dict[str, ThreadRelay] = {}
        occupied = set(agent_names)
        for raw_name, raw_cfg in (config or {}).items():
            name = str(raw_name).strip().lower()
            if not _HANDLE_RE.fullmatch(name):
                raise ValueError(
                    f"Invalid thread relay name {raw_name!r}; use lowercase letters, digits, and hyphens."
                )
            if name in occupied or name in {"all", "both"}:
                raise ValueError(f"Thread relay {name!r} conflicts with an existing agent.")
            if not isinstance(raw_cfg, dict):
                raise ValueError(f"Thread relay {name!r} must be a TOML table.")

            thread_id = str(raw_cfg.get("thread_id", "")).strip()
            try:
                uuid.UUID(thread_id)
            except (AttributeError, ValueError):
                raise ValueError(f"Thread relay {name!r} requires a UUID thread_id.") from None

            raw_cwd = str(raw_cfg.get("cwd", ".")).strip()
            cwd = Path(raw_cwd).expanduser()
            if not cwd.is_absolute():
                cwd = root / cwd
            timeout = raw_cfg.get("timeout_seconds", 600)
            if not isinstance(timeout, int) or not 10 <= timeout <= 3600:
                raise ValueError(f"Thread relay {name!r} timeout_seconds must be an integer from 10 to 3600.")

            command = str(raw_cfg.get("command", "codex")).strip()
            if not command:
                raise ValueError(f"Thread relay {name!r} requires a command.")
            self._relays[name] = ThreadRelay(
                name=name,
                thread_id=thread_id,
                cwd=cwd.resolve(),
                command=command,
                label=str(raw_cfg.get("label", f"Codex · {name}")).strip() or name,
                color=str(raw_cfg.get("color", "#10a37f")),
                timeout_seconds=timeout,
            )
            occupied.add(name)

    def get(self, name: str) -> ThreadRelay | None:
        return self._relays.get(name.lower())

    @property
    def names(self) -> list[str]:
        return list(self._relays)

    def materialize(self, config: dict) -> None:
        """Expose each relay as a normal, individually routable room member."""
        agents = config.setdefault("agents", {})
        for relay in self._relays.values():
            agents[relay.name] = {
                "type": "thread_relay",
                "provider": "codex",
                "command": relay.command,
                "cwd": str(relay.cwd),
                "thread_id": relay.thread_id,
                "label": relay.label,
                "color": relay.color,
                "timeout_seconds": relay.timeout_seconds,
            }


def materialize_thread_relays(config: dict, root: Path) -> ThreadRelays:
    relays = ThreadRelays(config.get("thread_relays"), set(config.get("agents", {})), root)
    relays.materialize(config)
    return relays
