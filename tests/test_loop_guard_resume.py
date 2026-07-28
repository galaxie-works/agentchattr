"""Compatibility coverage after removal of the agent-to-agent loop guard."""

import asyncio
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app


class UnrestrictedRoutingCompatibilityTests(unittest.TestCase):
    def test_resume_command_is_a_compatibility_noop(self):
        fake_router = mock.Mock()
        fake_store = mock.Mock()

        with mock.patch.object(app, "router", fake_router), \
             mock.patch.object(app, "store", fake_store), \
             mock.patch.object(app, "broadcast_status", new=mock.AsyncMock()) as status, \
             mock.patch.object(app, "_handle_new_message", new=mock.AsyncMock()) as handle:
            asyncio.run(app._resume_agent_conversation("general", "user"))

        fake_router.continue_routing.assert_not_called()
        fake_store.add.assert_called_once_with(
            "system",
            "Routing is unrestricted; /continue is no longer needed.",
            msg_type="system",
            channel="general",
        )
        status.assert_awaited_once()
        handle.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
