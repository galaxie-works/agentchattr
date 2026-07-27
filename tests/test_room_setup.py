"""Tests for the room-wizard execution plan."""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from room_setup import RoomSetupError, available_agents, build_room_plan


CLAUDE_ID = "2105f2d0-351f-4e8b-bdd5-0668ec3112e4"


class RoomSetupPlanTests(unittest.TestCase):
    def setUp(self):
        self.config = {
            "agents": {
                "codex": {"command": "codex", "cwd": ".", "label": "Codex", "color": "#10a37f"},
                "claude": {"command": "claude", "cwd": ".", "label": "Claude", "color": "#da7756"},
                "gemini": {"command": "gemini", "cwd": ".", "label": "Gemini"},
            }
        }

    def test_exposes_base_agents_and_not_runtime_relays(self):
        self.config["agents"]["codex-main"] = {"type": "thread_relay"}
        agents = available_agents(self.config)
        self.assertEqual([agent["name"] for agent in agents], ["claude", "codex", "gemini"])
        self.assertTrue(next(agent for agent in agents if agent["name"] == "claude")["resumable"])
        self.assertFalse(next(agent for agent in agents if agent["name"] == "gemini")["resumable"])

    def test_builds_codex_thread_relay_and_resumed_claude_wrapper(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = build_room_plan(self.config, {
                "title": "Galaxie room",
                "agents": [
                    {"name": "codex", "mode": "custom", "target": "saved-codex-thread", "cwd": str(root)},
                    {"name": "claude", "mode": "custom", "target": CLAUDE_ID, "cwd": str(root)},
                ],
            }, root)

        self.assertEqual(plan.thread_relays["codex-room"]["target"], "saved-codex-thread")
        self.assertEqual(plan.room_agents["claude-room"]["cwd"], str(root.resolve()))
        self.assertIn(("wrapper", "claude-room", ("--resume", CLAUDE_ID)), [
            (item.kind, item.agent, item.extra_args) for item in plan.launches
        ])

    def test_rejects_non_uuid_claude_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(RoomSetupError, "Claude"):
                build_room_plan(self.config, {
                    "agents": [{"name": "claude", "mode": "custom", "target": "not-a-session", "cwd": tmp}],
                }, Path(tmp))


if __name__ == "__main__":
    unittest.main()
