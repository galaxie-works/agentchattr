"""Opt-in project catalog and isolated Codex/Claude room members.

The catalog is deliberately declared in ``config.local.toml``.  Provider
session databases and deep links are private implementation details, so this
module never reads them.  A catalog entry materializes one registered
AgentChattr agent per provider, with a deterministic name such as
``codex-website`` and a working directory set to the declared project path.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import re


_HANDLE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,30}$")


@dataclass(frozen=True)
class Project:
    """A locally registered project root."""

    name: str
    path: Path
    label: str


@dataclass(frozen=True)
class ProjectMember:
    """A provider process bound to one registered project."""

    project: Project
    provider: str
    agent_name: str
    label: str
    color: str | None
    teammate: str
    relay_alias: str


class ProjectCatalog:
    """Validate the ``[projects]`` config and materialize its members."""

    def __init__(self, projects: list[Project], members: list[ProjectMember]):
        self.projects = projects
        self.members = members

    @classmethod
    def from_config(cls, raw: dict | None, base_agents: dict, root: Path) -> "ProjectCatalog":
        projects: list[Project] = []
        members: list[ProjectMember] = []
        seen_agent_names = set(base_agents)
        seen_relays: set[str] = set()

        for raw_name, raw_project in (raw or {}).items():
            name = str(raw_name).strip().lower()
            if not _HANDLE_RE.fullmatch(name):
                raise ValueError(
                    f"Invalid project name {raw_name!r}; use lowercase letters, digits, and hyphens."
                )
            if not isinstance(raw_project, dict):
                raise ValueError(f"Project {name!r} must be a TOML table.")

            raw_path = str(raw_project.get("path", "")).strip()
            if not raw_path:
                raise ValueError(f"Project {name!r} requires a path.")
            path = Path(raw_path).expanduser()
            if not path.is_absolute():
                path = root / path
            path = path.resolve()
            label = str(raw_project.get("label", name)).strip() or name
            project = Project(name=name, path=path, label=label)
            projects.append(project)

            raw_members = raw_project.get("members", {})
            if not isinstance(raw_members, dict):
                raise ValueError(f"Project {name!r} members must be TOML tables.")
            for raw_provider, raw_member in raw_members.items():
                provider = str(raw_provider).strip().lower()
                if provider not in base_agents:
                    raise ValueError(
                        f"Project member {provider!r} in {name!r} has no matching [agents.{provider}] provider."
                    )
                if not isinstance(raw_member, dict):
                    raise ValueError(f"Project member {provider!r} in {name!r} must be a TOML table.")

                agent_name = f"{provider}-{name}"
                if not _HANDLE_RE.fullmatch(agent_name):
                    raise ValueError(f"Project member name {agent_name!r} is too long or invalid.")
                if agent_name in seen_agent_names:
                    raise ValueError(f"Project member {agent_name!r} conflicts with an existing agent.")
                seen_agent_names.add(agent_name)

                teammate = str(raw_member.get("teammate", "")).strip()
                relay_alias = str(raw_member.get("relay_alias", f"{name}-{provider}")).strip().lower()
                if teammate:
                    if not _HANDLE_RE.fullmatch(relay_alias):
                        raise ValueError(
                            f"Relay alias {relay_alias!r} for {agent_name!r} is invalid."
                        )
                    if relay_alias in seen_relays or relay_alias in seen_agent_names or relay_alias in {"all", "both"}:
                        raise ValueError(f"Relay alias {relay_alias!r} conflicts with an agent or another relay.")
                    seen_relays.add(relay_alias)

                member_label = str(raw_member.get("label", f"{provider.title()} · {label}")).strip()
                color = raw_member.get("color")
                if color is not None:
                    color = str(color)
                members.append(ProjectMember(
                    project=project,
                    provider=provider,
                    agent_name=agent_name,
                    label=member_label or agent_name,
                    color=color,
                    teammate=teammate,
                    relay_alias=relay_alias,
                ))

        return cls(projects, members)

    def materialize(self, config: dict) -> None:
        """Add project members and their optional native teammate routes in-place."""
        agents = config.setdefault("agents", {})
        relays = config.setdefault("relays", {})
        for member in self.members:
            base = dict(agents[member.provider])
            base.update({
                "provider": member.provider,
                "cwd": str(member.project.path),
                "label": member.label,
            })
            if member.color:
                base["color"] = member.color
            agents[member.agent_name] = base

            if member.teammate:
                if member.relay_alias in relays:
                    raise ValueError(f"Generated relay {member.relay_alias!r} conflicts with [relays].")
                relays[member.relay_alias] = {
                    "agent": member.agent_name,
                    "teammate": member.teammate,
                    "project": member.project.name,
                }


def materialize_projects(config: dict, root: Path) -> ProjectCatalog:
    """Create a catalog from config and add its members to ``config``."""
    catalog = ProjectCatalog.from_config(config.get("projects"), config.get("agents", {}), root)
    catalog.materialize(config)
    return catalog


def _main() -> int:
    parser = argparse.ArgumentParser(description="List locally registered AgentChattr projects.")
    parser.add_argument("command", nargs="?", choices=["list"], default="list")
    args = parser.parse_args()
    del args

    from config_loader import load_config
    config = load_config(Path(__file__).parent)
    catalog = ProjectCatalog.from_config(config.get("projects"), {
        name: cfg for name, cfg in config.get("agents", {}).items() if "provider" not in cfg
    }, Path(__file__).parent)
    if not catalog.projects:
        print("No projects registered. Add [projects.NAME] to config.local.toml.")
        return 0
    for project in catalog.projects:
        state = "ready" if project.path.is_dir() else "missing"
        print(f"{project.name}\t{project.path}\t{state}")
        for member in (m for m in catalog.members if m.project.name == project.name):
            relay = f"@{member.relay_alias}" if member.teammate else "(no native relay)"
            print(f"  {member.agent_name}\t{member.provider}\t{relay}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
