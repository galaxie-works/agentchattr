import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from relay import RelayRoutes
from router import Router


class RelayRouteTests(unittest.TestCase):
    def setUp(self):
        self.routes = RelayRoutes(
            {"codex-review": {"agent": "codex", "teammate": "reviewer"}},
            ["claude", "codex"],
        )

    def test_alias_routes_to_the_configured_agent(self):
        router = Router(["claude", "codex"], default_mention="none", aliases=self.routes.aliases)
        self.assertEqual(router.get_targets("user", "@codex-review check this"), ["codex"])

    def test_alias_is_case_insensitive_and_keeps_the_route(self):
        found = self.routes.routes_in("please ask @CODEX-REVIEW to inspect it")
        self.assertEqual(found, [self.routes._routes["codex-review"]])

    def test_native_prompt_has_correlation_without_echoing_message_content(self):
        prompt = self.routes.build_prompt(
            self.routes._routes["codex-review"],
            {"id": 42, "channel": "review", "sender": "user", "text": "untrusted payload"},
        )
        self.assertIn("message #42", prompt)
        self.assertIn("teammate 'reviewer'", prompt)
        self.assertNotIn("untrusted payload", prompt)

    def test_rejects_alias_that_conflicts_with_an_agent(self):
        with self.assertRaises(ValueError):
            RelayRoutes({"codex": {"agent": "codex", "teammate": "reviewer"}}, ["codex"])

    def test_agent_reply_chains_are_unrestricted(self):
        router = Router(
            ["claude", "codex"], default_mention="none", max_hops=1, aliases=self.routes.aliases
        )
        self.assertEqual(router.get_targets("claude", "@codex-review please review"), ["codex"])
        self.assertEqual(router.get_targets("codex", "@claude follow up", message_id=42), ["claude"])
        self.assertFalse(router.is_paused())
        self.assertIsNone(router.continue_routing())
        self.assertFalse(router.is_paused())

    def test_many_agent_hops_never_pause(self):
        router = Router(["claude", "codex"], default_mention="none", max_hops=1)
        for message_id in range(100):
            sender, target = ("claude", "codex") if message_id % 2 == 0 else ("codex", "claude")
            self.assertEqual(
                router.get_targets(sender, f"@{target} continue", message_id=message_id),
                [target],
            )
        self.assertFalse(router.is_paused())


if __name__ == "__main__":
    unittest.main()
