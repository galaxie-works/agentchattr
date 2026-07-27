import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app


class _Registry:
    def get_instance(self, name):
        return {"name": name, "base": "codex"} if name == "codex-2" else None


class RelayTargetPromptTests(unittest.TestCase):
    def setUp(self):
        self.original_registry = app.registry
        app.registry = _Registry()

    def tearDown(self):
        app.registry = self.original_registry

    def test_renamed_instance_uses_its_base_agent_relay_prompt(self):
        self.assertEqual(
            app._relay_prompt_for_target("codex-2", {"codex": "relay prompt"}),
            "relay prompt",
        )

    def test_unknown_target_has_no_relay_prompt(self):
        self.assertEqual(app._relay_prompt_for_target("claude", {"codex": "relay prompt"}), "")


if __name__ == "__main__":
    unittest.main()
