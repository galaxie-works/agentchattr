"""Tests for the room-wizard execution plan."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from claude_sessions import (
    CLAUDE_ROOM_RESUME_PROMPT,
    _termination_root,
    active_session_ids,
    active_sessions,
    reconcile_workspace_trust,
    resume_target,
    room_resume_args,
)
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
        self.assertTrue(plan.thread_relays["codex-room"]["singleton"])
        self.assertEqual(plan.room_agents["claude-room"]["cwd"], str(root.resolve()))
        self.assertTrue(plan.room_agents["claude-room"]["singleton"])
        self.assertIn(("wrapper", "claude-room", room_resume_args(CLAUDE_ID)), [
            (item.kind, item.agent, item.extra_args) for item in plan.launches
        ])

    def test_rejects_non_uuid_claude_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(RoomSetupError, "Claude"):
                build_room_plan(self.config, {
                    "agents": [{"name": "claude", "mode": "custom", "target": "not-a-session", "cwd": tmp}],
                }, Path(tmp))

    def test_reads_only_live_claude_session_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            sessions = Path(tmp) / "sessions"
            sessions.mkdir()
            (sessions / "101.json").write_text('{"sessionId":"live-session","pid":101}', encoding="utf-8")
            (sessions / "102.json").write_text('{"sessionId":"stale-session","pid":102}', encoding="utf-8")

            active = active_session_ids(Path(tmp), process_is_running=lambda pid: pid == 101)

        self.assertEqual(active, {"live-session"})

    def test_keeps_all_live_pids_for_the_same_claude_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            sessions = Path(tmp) / "sessions"
            sessions.mkdir()
            (sessions / "101.json").write_text('{"sessionId":"same-session","pid":101}', encoding="utf-8")
            (sessions / "102.json").write_text('{"sessionId":"same-session","pid":102}', encoding="utf-8")

            active = active_sessions(Path(tmp), process_is_running=lambda _pid: True)

        self.assertEqual(active, {"same-session": {101, 102}})

    def test_terminating_a_wrapped_cli_uses_its_wrapper_root(self):
        processes = {
            400: (300, "claude --resume session-id"),
            300: (1, "python wrapper.py claude-room --resume session-id"),
        }
        self.assertEqual(_termination_root(400, processes.get), 300)

    def test_extracts_claude_resume_target_from_wrapper_arguments(self):
        self.assertEqual(resume_target(list(room_resume_args(CLAUDE_ID))), CLAUDE_ID)
        self.assertEqual(resume_target([f"--resume={CLAUDE_ID}"]), CLAUDE_ID)
        self.assertIsNone(resume_target(["--no-restart"]))

    def test_claude_room_resume_includes_a_non_empty_bootstrap_prompt(self):
        self.assertEqual(room_resume_args(CLAUDE_ID)[:2], ("--resume", CLAUDE_ID))
        self.assertEqual(room_resume_args(CLAUDE_ID)[2], CLAUDE_ROOM_RESUME_PROMPT)
        self.assertTrue(CLAUDE_ROOM_RESUME_PROMPT.strip())

    def test_repairs_conflicting_slash_variant_workspace_trust(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / ".claude.json"
            backslash = str(root).replace("/", "\\")
            forward = str(root).replace("\\", "/")
            config_path.write_text(json.dumps({
                "projects": {
                    backslash: {"hasTrustDialogAccepted": True},
                    forward: {"hasTrustDialogAccepted": False},
                }
            }), "utf-8")

            self.assertTrue(reconcile_workspace_trust(root, config_path))
            projects = json.loads(config_path.read_text("utf-8"))["projects"]
            self.assertTrue(all(item["hasTrustDialogAccepted"] for item in projects.values()))

    def test_does_not_auto_trust_a_new_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / ".claude.json"
            config_path.write_text(json.dumps({
                "projects": {str(root): {"hasTrustDialogAccepted": False}}
            }), "utf-8")

            self.assertFalse(reconcile_workspace_trust(root, config_path))
            payload = json.loads(config_path.read_text("utf-8"))
            self.assertFalse(payload["projects"][str(root)]["hasTrustDialogAccepted"])


if __name__ == "__main__":
    unittest.main()
