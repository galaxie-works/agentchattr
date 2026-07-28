"""Message routing based on @mentions."""

import re


class Router:
    def __init__(self, agent_names: list[str], default_mention: str = "both",
                 max_hops: int = 4, online_checker=None, aliases: dict[str, str] | None = None):
        self.agent_names = set(n.lower() for n in agent_names)
        self.aliases = {name.lower(): target.lower() for name, target in (aliases or {}).items()}
        self.default_mention = default_mention
        # Retained as a no-op constructor parameter so older integrations do
        # not break. Agent conversations are intentionally unrestricted.
        self.max_hops = max_hops
        self._online_checker = online_checker  # callable() -> set of online agent names
        self._build_pattern()

    def _build_pattern(self):
        # Sort longest-first so "gemini-2" is tried before "gemini"
        names = [re.escape(n) for n in sorted(self.agent_names | set(self.aliases), key=len, reverse=True)]
        alternatives = "|".join(names + ["both", "all"])
        self._mention_re = re.compile(
            rf"@({alternatives})(?![\w-])", re.IGNORECASE
        )

    def parse_mentions(self, text: str) -> list[str]:
        mentions = set()
        for match in self._mention_re.finditer(text):
            name = match.group(1).lower()
            if name in ("both", "all"):
                # Only tag online agents when using @all
                if self._online_checker:
                    online = self._online_checker()
                    mentions.update(n for n in self.agent_names if n in online)
                else:
                    mentions.update(self.agent_names)
            else:
                mentions.add(self.aliases.get(name, name))
        return list(mentions)

    def _is_agent(self, sender: str) -> bool:
        return sender.lower() in self.agent_names

    def get_targets(
        self,
        sender: str,
        text: str,
        channel: str = "general",
        message_id: int | None = None,
    ) -> list[str]:
        """Determine which agents should receive this message."""
        mentions = self.parse_mentions(text)

        if not self._is_agent(sender):
            if not mentions:
                if self.default_mention in ("both", "all"):
                    return list(self.agent_names)
                elif self.default_mention == "none":
                    return []
                return [self.default_mention]
            return mentions
        else:
            # Only route if explicit @mention
            if not mentions:
                return []
            # Don't route back to self
            return [m for m in mentions if m != sender]

    def continue_routing(self, channel: str = "general"):
        """Compatibility no-op: routing is never paused."""
        return None

    def is_paused(self, channel: str = "general") -> bool:
        return False

    def is_guard_emitted(self, channel: str = "general") -> bool:
        return False

    def set_guard_emitted(self, channel: str = "general"):
        return None

    def update_agents(self, names: list[str]):
        """Replace the agent name set and rebuild the mention regex."""
        self.agent_names = set(n.lower() for n in names)
        self._build_pattern()
