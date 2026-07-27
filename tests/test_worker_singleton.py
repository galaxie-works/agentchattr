import tempfile
import unittest
from pathlib import Path

from worker_singleton import WorkerAlreadyRunning, acquire_worker_lock


class WorkerSingletonTests(unittest.TestCase):
    def test_same_worker_cannot_be_acquired_twice(self):
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            first = acquire_worker_lock("codex-room", data_dir)
            try:
                with self.assertRaises(WorkerAlreadyRunning):
                    acquire_worker_lock("codex-room", data_dir)
            finally:
                first.release()

            replacement = acquire_worker_lock("codex-room", data_dir)
            replacement.release()

    def test_different_worker_names_have_independent_locks(self):
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            codex = acquire_worker_lock("codex-room", data_dir)
            claude = acquire_worker_lock("claude-room", data_dir)
            claude.release()
            codex.release()


if __name__ == "__main__":
    unittest.main()
