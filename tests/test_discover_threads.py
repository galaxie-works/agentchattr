"""Regression coverage for local Codex/Claude thread discovery."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from discover_threads import discover_codex_threads


class CodexDiscoveryTests(unittest.TestCase):
    def test_reads_cwd_from_rollout_session_metadata_when_index_omits_it(self):
        thread_id = "019fa400-ed55-73e1-9209-08b172015054"
        with tempfile.TemporaryDirectory() as tmp:
            codex_home = Path(tmp)
            (codex_home / "session_index.jsonl").write_text(
                json.dumps({"id": thread_id, "thread_name": "Onboarding", "updated_at": "2026-07-27T14:36:09Z"}) + "\n",
                encoding="utf-8",
            )
            session_dir = codex_home / "sessions" / "2026" / "07" / "27"
            session_dir.mkdir(parents=True)
            (session_dir / f"rollout-2026-07-27T11-35-52-{thread_id}.jsonl").write_text(
                json.dumps({"type": "session_meta", "payload": {"id": thread_id, "cwd": "C:\\dev\\agentchattr"}}) + "\n",
                encoding="utf-8",
            )

            threads = discover_codex_threads(codex_home)

        self.assertEqual(threads[0]["cwd"], "C:\\dev\\agentchattr")


if __name__ == "__main__":
    unittest.main()
