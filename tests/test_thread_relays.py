"""Tests for explicit persisted-Codex-thread relay configuration and parsing."""

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from thread_relay import build_turn_prompt, extract_final_message, run_turn
from thread_relays import ThreadRelay, ThreadRelays, materialize_thread_relays


THREAD_ID = "019fa400-ed55-73e1-9209-08b172015054"


class ThreadRelayConfigTests(unittest.TestCase):
    def test_materializes_a_distinct_routable_agent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = {
                "agents": {"codex": {"command": "codex", "cwd": "."}},
                "thread_relays": {
                    "codex-main": {
                        "thread_id": THREAD_ID,
                        "cwd": "workspace",
                        "label": "Main Codex",
                    },
                },
            }
            relays = materialize_thread_relays(config, root)

        self.assertEqual(relays.names, ["codex-main"])
        self.assertEqual(config["agents"]["codex-main"]["type"], "thread_relay")
        self.assertTrue(config["agents"]["codex-main"]["singleton"])
        self.assertEqual(config["agents"]["codex-main"]["session_id"], THREAD_ID)
        self.assertEqual(config["agents"]["codex-main"]["cwd"], str((root / "workspace").resolve()))

    def test_codex_accepts_a_saved_thread_name_but_claude_requires_a_uuid(self):
        relays = ThreadRelays({"codex-main": {"target": "main-room-thread"}}, set(), ROOT)
        self.assertEqual(relays.get("codex-main").session_id, "main-room-thread")
        with self.assertRaisesRegex(ValueError, "Claude"):
            ThreadRelays({"claude-main": {"provider": "claude", "target": "main-room"}}, set(), ROOT)

    def test_rejects_conflicting_agent_name(self):
        with self.assertRaisesRegex(ValueError, "conflicts"):
            ThreadRelays({"codex": {"thread_id": THREAD_ID}}, {"codex"}, ROOT)

    def test_materializes_a_claude_session_relay(self):
        config = {
            "agents": {},
            "thread_relays": {
                "claude-main": {"provider": "claude", "session_id": THREAD_ID},
            },
        }
        materialize_thread_relays(config, ROOT)
        self.assertEqual(config["agents"]["claude-main"]["provider"], "claude")
        self.assertEqual(config["agents"]["claude-main"]["session_id"], THREAD_ID)


class ThreadRelayWorkerTests(unittest.TestCase):
    def test_turn_prompt_preserves_correlation_and_untrusted_text(self):
        prompt = build_turn_prompt({"channel": "general", "message_id": 42, "text": "@codex-main\nhi"})
        self.assertTrue(prompt.startswith("ROOM MESSAGE #42 in #general: @codex-main hi."))
        self.assertNotIn("\n", prompt)

    def test_extracts_only_the_last_completed_agent_message(self):
        stdout = "\n".join([
            '{"type":"item.completed","item":{"type":"agent_message","text":"first"}}',
            '{"type":"item.completed","item":{"type":"command_execution","command":"dir"}}',
            '{"type":"item.completed","item":{"type":"agent_message","text":"last"}}',
        ])
        self.assertEqual(extract_final_message(stdout), "last")

    def test_run_turn_resumes_only_the_configured_thread_with_full_control(self):
        with tempfile.TemporaryDirectory() as tmp:
            relay = ThreadRelay(
                name="codex-main", provider="codex", session_id=THREAD_ID, cwd=Path(tmp), command="codex",
                label="Main", color="#10a37f", timeout_seconds=30,
            )
            completed = SimpleNamespace(
                stdout='{"type":"item.completed","item":{"type":"agent_message","text":"ok"}}\n',
                stderr="", returncode=0,
            )
            with mock.patch("thread_relay.shutil.which", return_value="C:/bin/codex"), \
                 mock.patch("thread_relay.subprocess.run", return_value=completed) as run:
                answer, error = run_turn(relay, "relay prompt")

        self.assertEqual((answer, error), ("ok", ""))
        args = run.call_args.args[0]
        self.assertEqual(args[:6], [
            "C:/bin/codex", "exec", "--json", "--dangerously-bypass-approvals-and-sandbox",
            "--skip-git-repo-check", "resume",
        ])
        self.assertEqual(args[6], THREAD_ID)
        self.assertEqual(run.call_args.kwargs["encoding"], "utf-8")

    def test_extracts_claude_print_result(self):
        self.assertEqual(extract_final_message('{"result":"Claude reply"}', "claude"), "Claude reply")

    def test_run_turn_resumes_the_configured_claude_session_with_full_control(self):
        with tempfile.TemporaryDirectory() as tmp:
            relay = ThreadRelay(
                name="claude-main", provider="claude", session_id=THREAD_ID, cwd=Path(tmp), command="claude",
                label="Main", color="#da7756", timeout_seconds=30,
            )
            completed = SimpleNamespace(stdout='{"result":"ok"}', stderr="", returncode=0)
            with mock.patch("thread_relay.shutil.which", return_value="C:/bin/claude"), \
                 mock.patch("thread_relay.subprocess.run", return_value=completed) as run:
                answer, error = run_turn(relay, "relay prompt")

        self.assertEqual((answer, error), ("ok", ""))
        self.assertEqual(run.call_args.args[0], [
            "C:/bin/claude", "--print", "--output-format", "json", "--resume", THREAD_ID,
            "--dangerously-skip-permissions", "relay prompt",
        ])


if __name__ == "__main__":
    unittest.main()
