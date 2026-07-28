"""Tests for workspace trust checks and app-owned process cleanup."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app
from provider_preflight import (
    ProviderPreflightTarget,
    codex_workspace_is_trusted,
    full_control_args,
    json_folder_workspace_is_trusted,
    pending_trust,
    preflight_blockers,
)


class ProviderTrustTests(unittest.TestCase):
    def test_codex_requires_an_exact_trusted_project_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "config.toml"
            config_path.write_text(
                f'[projects."{root.as_posix()}"]\ntrust_level = "trusted"\n',
                encoding="utf-8",
            )

            self.assertTrue(codex_workspace_is_trusted(root, config_path))
            self.assertFalse(codex_workspace_is_trusted(root / "child", config_path))

    def test_folder_trust_uses_the_most_specific_matching_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            child = root / "customer"
            child.mkdir()
            trust_path = root / "trustedFolders.json"
            trust_path.write_text(json.dumps({
                str(root): "TRUST_FOLDER",
                str(child): "DO_NOT_TRUST",
            }), encoding="utf-8")

            self.assertFalse(json_folder_workspace_is_trusted(child, trust_path))

    def test_verified_full_control_profiles_are_explicit(self):
        self.assertEqual(
            full_control_args("codex"),
            ("--dangerously-bypass-approvals-and-sandbox",),
        )
        self.assertEqual(
            full_control_args("claude"),
            ("--dangerously-skip-permissions",),
        )
        self.assertIsNone(full_control_args("unknown-provider"))

    def test_unknown_full_control_profile_blocks_launch(self):
        target = ProviderPreflightTarget(
            provider="unknown",
            label="Unknown",
            command=sys.executable,
            cwd=ROOT,
            full_control=None,
            trust=None,
        )
        self.assertIn("no verified full-control profile", preflight_blockers([target])[0])

    def test_missing_working_directory_blocks_launch(self):
        target = ProviderPreflightTarget(
            provider="test",
            label="Test",
            command=sys.executable,
            cwd=ROOT / "definitely-missing-workspace",
            full_control=("--full-control",),
            trust=None,
        )
        self.assertIn("working directory does not exist", preflight_blockers([target])[0])

    def test_untrusted_target_is_returned_for_visible_bootstrap(self):
        target = ProviderPreflightTarget(
            provider="test",
            label="Test",
            command=sys.executable,
            cwd=ROOT,
            full_control=("--full-control",),
            trust="unsupported-test-trust",
        )
        self.assertEqual(pending_trust([target]), [target])


class RoomWorkerShutdownTests(unittest.TestCase):
    def test_saved_room_members_include_standard_and_custom_colleagues(self):
        settings = {
            "room_members": [
                {
                    "provider": "gemini",
                    "mode": "standard",
                    "agent": "gemini",
                    "cwd": str(ROOT),
                },
                {
                    "provider": "codex",
                    "mode": "custom",
                    "agent": "codex-room",
                    "id": "saved-thread",
                    "cwd": str(ROOT),
                },
            ],
        }
        with mock.patch.object(app, "room_settings", settings):
            members = app._current_room_members()

        self.assertEqual([item["agent"] for item in members], ["gemini", "codex-room"])
        self.assertEqual([item["mode"] for item in members], ["standard", "custom"])

    def test_shutdown_closes_preflight_and_tracked_and_adopted_workers(self):
        preflight = mock.Mock(id="preflight")
        process = SimpleNamespace(pid=101, poll=lambda: None)
        fake_registry = mock.Mock()
        fake_registry.get_instances_for.return_value = [{"name": "claude-room"}]
        workers = {"claude-room": process}
        specs = {("wrapper", "claude-room"), ("thread_relay", "codex-room")}
        sessions = {"preflight": preflight}

        def roots(_kind, agent):
            return [{"pid": 202}] if agent == "codex-room" else []

        with mock.patch.object(app, "provider_preflight_sessions", sessions), \
             mock.patch.object(app, "room_workers", workers), \
             mock.patch.object(app, "managed_room_workers", specs), \
             mock.patch.object(app, "registry", fake_registry), \
             mock.patch.object(app, "_room_worker_roots", side_effect=roots), \
             mock.patch.object(app, "_terminate_worker_tree") as terminate:
            app.shutdown_room_workers()

        preflight.close.assert_called_once_with()
        self.assertEqual({call.args[0] for call in terminate.call_args_list}, {101, 202})
        self.assertEqual(workers, {})
        self.assertEqual(specs, set())
        self.assertEqual(sessions, {})
        fake_registry.deregister.assert_any_call("claude-room", reclaimable=False)


if __name__ == "__main__":
    unittest.main()
