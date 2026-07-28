"""Regression coverage for resuming the exact turn blocked by the loop guard."""

import asyncio
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app


class LoopGuardResumeTests(unittest.TestCase):
    def test_resume_replays_blocked_message_without_rebroadcast_marker_loss(self):
        pending = {
            "sender": "codex-room",
            "text": "@claude-room continue the handoff",
            "message_id": 74,
        }
        fake_router = mock.Mock()
        fake_router.continue_routing.return_value = pending
        fake_store = mock.Mock()

        with mock.patch.object(app, "router", fake_router), \
             mock.patch.object(app, "store", fake_store), \
             mock.patch.object(app, "broadcast_status", new=mock.AsyncMock()) as status, \
             mock.patch.object(app, "_handle_new_message", new=mock.AsyncMock()) as handle:
            asyncio.run(app._resume_agent_conversation("general", "user"))

        fake_router.continue_routing.assert_called_once_with("general")
        fake_store.add.assert_called_once_with(
            "system",
            "Resuming agent conversation from message #74...",
            msg_type="system",
            channel="general",
        )
        status.assert_awaited_once()
        handle.assert_awaited_once_with({
            "id": 74,
            "sender": "codex-room",
            "text": "@claude-room continue the handoff",
            "type": "chat",
            "channel": "general",
            "_routing_replay": True,
        })

    def test_resume_without_pending_turn_is_explicit(self):
        fake_router = mock.Mock()
        fake_router.continue_routing.return_value = None
        fake_store = mock.Mock()

        with mock.patch.object(app, "router", fake_router), \
             mock.patch.object(app, "store", fake_store), \
             mock.patch.object(app, "broadcast_status", new=mock.AsyncMock()), \
             mock.patch.object(app, "_handle_new_message", new=mock.AsyncMock()) as handle:
            asyncio.run(app._resume_agent_conversation("general", "user"))

        handle.assert_not_awaited()
        self.assertIn(
            "there was no blocked agent message to replay",
            fake_store.add.call_args.args[1],
        )


if __name__ == "__main__":
    unittest.main()
