import unittest

from app import _matching_worker_roots, _worker_command_matches


class RoomWorkerReconciliationTests(unittest.TestCase):
    def test_matches_only_exact_worker_and_agent(self):
        self.assertTrue(_worker_command_matches(
            r"C:\Python\python.exe C:\dev\agentchattr\thread_relay.py codex-room",
            "thread_relay",
            "codex-room",
        ))
        self.assertFalse(_worker_command_matches(
            r"C:\Python\python.exe C:\dev\agentchattr\thread_relay.py codex-room-2",
            "thread_relay",
            "codex-room",
        ))
        self.assertFalse(_worker_command_matches(
            r"C:\Python\python.exe C:\dev\agentchattr\wrapper.py codex-room",
            "thread_relay",
            "codex-room",
        ))

    def test_collapses_venv_launcher_child_but_preserves_real_duplicates(self):
        command = r"C:\Python\python.exe C:\dev\agentchattr\thread_relay.py codex-room"
        processes = [
            {"pid": 10, "parent_pid": 1, "created": "2026-01-01", "command": command},
            {"pid": 11, "parent_pid": 10, "created": "2026-01-01", "command": command},
            {"pid": 20, "parent_pid": 1, "created": "2026-01-02", "command": command},
            {"pid": 21, "parent_pid": 20, "created": "2026-01-02", "command": command},
        ]

        roots = _matching_worker_roots(processes, "thread_relay", "codex-room")

        self.assertEqual([process["pid"] for process in roots], [10, 20])


if __name__ == "__main__":
    unittest.main()
