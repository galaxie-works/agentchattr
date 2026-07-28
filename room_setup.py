"""Validation and execution plan for the first-run room wizard."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from claude_sessions import room_resume_args
from provider_preflight import full_control_args
from thread_relays import validate_target


class RoomSetupError(ValueError):
    """A user-correctable room setup error."""


@dataclass(frozen=True)
class LaunchSpec:
    kind: str  # "wrapper" or "thread_relay"
    agent: str
    extra_args: tuple[str, ...] = ()


@dataclass(frozen=True)
class RoomPlan:
    title: str
    description: str
    room_agents: dict[str, dict]
    thread_relays: dict[str, dict]
    launches: tuple[LaunchSpec, ...]


def available_agents(config: dict) -> list[dict]:
    """Expose provider capabilities that have a configured app-level runner."""
    from discover_threads import providers

    result = []
    for capability in providers():
        name = capability["name"]
        cfg = config.get("agents", {}).get(name)
        if not isinstance(cfg, dict) or cfg.get("type") == "thread_relay":
            continue
        result.append({
            "name": name,
            "provider": name,
            "label": capability["label"],
            "color": str(cfg.get("color", "#888888")),
            "cwd": str(cfg.get("cwd", ".")),
            "resumable": bool(capability["resumable"]),
            "address": capability["address"],
            "store_hint": capability["store_hint"],
        })
    return sorted(result, key=lambda item: item["label"].lower())


def _room_alias(provider: str) -> str:
    return f"{provider}-room"


def build_room_plan(config: dict, payload: Any, root: Path) -> RoomPlan:
    """Turn wizard data into explicit workers without discovering sessions."""
    if not isinstance(payload, dict):
        raise RoomSetupError("Room setup must be a JSON object.")
    selected = payload.get("agents")
    if not isinstance(selected, list) or not selected:
        raise RoomSetupError("Invite at least one colleague.")
    if len(selected) > 12:
        raise RoomSetupError("A room can have at most 12 configured colleagues.")

    available = {item["name"]: item for item in available_agents(config)}
    title = str(payload.get("title", "New room")).strip()[:80] or "New room"
    description = str(payload.get("description", "")).strip()[:240]
    room_agents: dict[str, dict] = {}
    thread_relays: dict[str, dict] = {}
    launches: list[LaunchSpec] = []
    seen: set[str] = set()
    custom_providers: set[str] = set()

    for raw in selected:
        if not isinstance(raw, dict):
            raise RoomSetupError("Every colleague must have a configuration.")
        name = str(raw.get("name", "")).strip().lower()
        if name not in available or name in seen:
            raise RoomSetupError("Choose each available colleague at most once.")
        seen.add(name)
        base = available[name]
        mode = str(raw.get("mode", "standard")).strip().lower()
        if mode == "standard":
            agent_cfg = config.get("agents", {}).get(name, {})
            if agent_cfg.get("type") == "api":
                launches.append(LaunchSpec("api", name))
            else:
                launches.append(LaunchSpec("wrapper", name, full_control_args(name, agent_cfg) or ()))
            continue
        if mode != "custom" or not base["resumable"]:
            raise RoomSetupError(f"{base['label']} does not support linking an existing conversation.")

        provider = base["provider"]
        try:
            target = validate_target(provider, raw.get("target", ""))
        except ValueError as exc:
            raise RoomSetupError(str(exc)) from None
        raw_cwd = str(raw.get("cwd", "")).strip()
        if not raw_cwd:
            raise RoomSetupError(f"{base['label']} needs a working directory.")
        cwd = Path(raw_cwd).expanduser()
        if not cwd.is_absolute():
            cwd = root / cwd
        cwd = cwd.resolve()
        if not cwd.is_dir():
            raise RoomSetupError(f"{base['label']} working directory does not exist: {cwd}")

        alias = _room_alias(provider)
        if provider in custom_providers:
            raise RoomSetupError(f"Choose only one custom {provider.title()} target per room.")
        custom_providers.add(provider)
        if provider == "codex":
            thread_relays[alias] = {
                "provider": "codex",
                "singleton": True,
                "target": target,
                "cwd": str(cwd),
                "label": f"Codex · {title}",
                "command": str(config.get("agents", {}).get(name, {}).get("command", "codex")),
                "color": base["color"],
                "timeout_seconds": 600,
                "full_control": True,
            }
            launches.append(LaunchSpec("thread_relay", alias))
        else:
            # Claude needs the wrapper, not the print-mode thread relay: the
            # wrapper owns the resumed CLI process and injects AgentChattr MCP.
            cfg = dict(config.get("agents", {}).get(name, {}))
            cfg.update({
                "provider": "claude",
                "singleton": True,
                "command": str(cfg.get("command", "claude")),
                "cwd": str(cwd),
                "label": f"Claude · {title}",
                "color": base["color"],
            })
            room_agents[alias] = cfg
            launches.append(LaunchSpec(
                "wrapper",
                alias,
                (*(full_control_args(provider, cfg) or ()), *room_resume_args(target)),
            ))

    return RoomPlan(title, description, room_agents, thread_relays, tuple(launches))
