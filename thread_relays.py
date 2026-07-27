"""Configuration for relays that address one persisted provider session.

Thread relays are intentionally explicit.  They never scan local session
storage, infer deep links, or accept a thread ID from a room message.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import uuid


_HANDLE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,30}$")


def runtime_relays_path(config: dict, root: Path) -> Path:
    """Return the local UI-owned relay settings file.

    It intentionally lives inside the ignored data directory, rather than
    rewriting a user's TOML file from the browser.
    """
    data_dir = Path(config.get("server", {}).get("data_dir", "./data"))
    if not data_dir.is_absolute():
        data_dir = root / data_dir
    return data_dir.resolve() / "thread_relays.json"


def validate_target(provider: str, target: object) -> str:
    """Validate one explicit resume target without discovering sessions."""
    value = str(target or "").strip()
    if not value or len(value) > 200 or any(ord(char) < 32 for char in value):
        raise ValueError("Thread relay target must be a non-empty single-line value.")
    if provider == "claude":
        try:
            uuid.UUID(value)
        except ValueError:
            raise ValueError("Claude thread relays require a resume session UUID.") from None
    return value


@dataclass(frozen=True)
class ThreadRelay:
    name: str
    provider: str
    session_id: str
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

            provider = str(raw_cfg.get("provider", "codex")).strip().lower()
            if provider not in {"codex", "claude"}:
                raise ValueError(f"Thread relay {name!r} provider must be 'codex' or 'claude'.")
            id_key = "thread_id" if provider == "codex" else "session_id"
            # ``target`` is the UI's provider-neutral representation. The
            # older per-provider keys remain supported for existing local TOML.
            session_id = validate_target(provider, raw_cfg.get("target", raw_cfg.get(id_key, "")))

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
                provider=provider,
                session_id=session_id,
                cwd=cwd.resolve(),
                command=command,
                label=str(raw_cfg.get("label", f"{provider.title()} · {name}")).strip() or name,
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
                "singleton": True,
                "provider": relay.provider,
                "command": relay.command,
                "cwd": str(relay.cwd),
                "target": relay.session_id,
                "session_id": relay.session_id,
                # Keep this field for existing integrations that inspected a
                # Codex relay before the provider-neutral ``target`` existed.
                "thread_id": relay.session_id if relay.provider == "codex" else "",
                "label": relay.label,
                "color": relay.color,
                "timeout_seconds": relay.timeout_seconds,
            }


def materialize_thread_relays(config: dict, root: Path) -> ThreadRelays:
    relays = ThreadRelays(config.get("thread_relays"), set(config.get("agents", {})), root)
    relays.materialize(config)
    return relays
