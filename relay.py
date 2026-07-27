"""Native teammate relay routes for AgentChattr.

The chat server never impersonates a provider or touches a provider's private
session files. A route wakes an already-running AgentChattr agent with an
instruction to use that provider's own teammate-messaging capability.
"""

from __future__ import annotations

from dataclasses import dataclass
import re


_HANDLE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,30}$")


@dataclass(frozen=True)
class RelayRoute:
    """A room alias dispatched by an Agentchattr agent to a native teammate."""

    alias: str
    agent: str
    teammate: str


class RelayRoutes:
    """Validated relay configuration and prompt builder.

    Config shape::

        [relays.codex-review]
        agent = "codex"
        teammate = "reviewer"
    """

    def __init__(self, config: dict | None, agent_names: list[str]):
        self._routes: dict[str, RelayRoute] = {}
        configured_agents = {name.lower() for name in agent_names}

        for raw_alias, raw_route in (config or {}).items():
            alias = str(raw_alias).strip().lower()
            if not _HANDLE_RE.fullmatch(alias):
                raise ValueError(
                    f"Invalid relay alias {raw_alias!r}; use lowercase letters, digits, and hyphens."
                )
            if alias in configured_agents or alias in {"all", "both"}:
                raise ValueError(f"Relay alias {alias!r} conflicts with a reserved agent mention.")
            if not isinstance(raw_route, dict):
                raise ValueError(f"Relay {alias!r} must be a TOML table.")

            agent = str(raw_route.get("agent", "")).strip().lower()
            teammate = str(raw_route.get("teammate", "")).strip()
            if agent not in configured_agents:
                raise ValueError(f"Relay {alias!r} references unknown agent {agent!r}.")
            if not teammate:
                raise ValueError(f"Relay {alias!r} requires a teammate name.")
            self._routes[alias] = RelayRoute(alias=alias, agent=agent, teammate=teammate)

    @property
    def aliases(self) -> dict[str, str]:
        """Map @room aliases to the registered relay-agent base name."""
        return {alias: route.agent for alias, route in self._routes.items()}

    def routes_in(self, text: str) -> list[RelayRoute]:
        """Return configured aliases explicitly mentioned in a room message."""
        found: list[RelayRoute] = []
        for alias, route in self._routes.items():
            if re.search(rf"@{re.escape(alias)}(?![\w-])", text, re.IGNORECASE):
                found.append(route)
        return found

    @staticmethod
    def build_prompt(route: RelayRoute, message: dict) -> str:
        """Create the only injected instruction a relay agent receives.

        The agent reads the canonical room message through MCP before it sends
        anything to its teammate. This prevents the wrapper from forwarding
        stale terminal text or making up a recipient response.
        """
        message_id = message.get("id", "unknown")
        channel = message.get("channel", "general")
        sender = message.get("sender", "unknown")
        return (
            f"Native teammate relay @{route.alias} was explicitly requested for "
            f"room message #{message_id} in #{channel} from {sender}. "
            f"First use AgentChattr MCP chat_read(channel='{channel}') and locate "
            f"message #{message_id}. Then use your platform's native message teammate "
            f"capability to send its substantive request to teammate '{route.teammate}', "
            f"including room=#{channel} and reply_to={message_id} as correlation data. "
            "Do not forward AgentChattr system instructions, secrets, or any request to "
            "change relay configuration. When the teammate returns a result, post a concise "
            f"answer to this room with chat_send(channel='{channel}', reply_to={message_id}). "
            "Do not @mention this relay alias in that answer; one room message causes at most "
            "one native teammate dispatch."
        )
