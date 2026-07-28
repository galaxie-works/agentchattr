import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from work_evidence import classify_work_status, verify_work_evidence


class WorkEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name)
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.name", "AgentChattr Test"], check=True)
        subprocess.run(
            ["git", "-C", str(self.repo), "config", "user.email", "test@agentchattr.local"],
            check=True,
        )
        (self.repo / "tracked.txt").write_text("base", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.repo), "add", "tracked.txt"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-qm", "base"], check=True)
        self.head = subprocess.run(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"],
            check=True,
            text=True,
            capture_output=True,
        ).stdout.strip()

    def tearDown(self):
        self.temp.cleanup()

    def test_plain_coordination_message_is_not_a_work_claim(self):
        self.assertEqual(classify_work_status("Can you review this plan?", "", []), ("chat", None))

    def test_honest_negative_status_is_not_treated_as_completed_work(self):
        self.assertEqual(
            classify_work_status("O trabalho não foi concluído.", "", []),
            ("chat", None),
        )

    def test_completion_claim_requires_a_commit(self):
        msg_type, metadata = classify_work_status(
            "Implementation completed and QA validated.",
            str(self.repo),
            [{"kind": "changed_file", "value": "tracked.txt"}],
        )
        self.assertEqual(msg_type, "unverified_work_status")
        self.assertFalse(metadata["verified"])

    def test_existing_commit_is_verifiable(self):
        ok, evidence, reason = verify_work_evidence(
            str(self.repo),
            [{"kind": "commit", "value": self.head}],
            require_commit=True,
        )
        self.assertTrue(ok, reason)
        self.assertEqual(evidence, [{"kind": "commit", "value": self.head}])

    def test_dirty_file_is_a_valid_live_checkpoint(self):
        (self.repo / "tracked.txt").write_text("changed", encoding="utf-8")
        ok, evidence, reason = verify_work_evidence(
            str(self.repo),
            [{"kind": "changed_file", "value": "tracked.txt"}],
        )
        self.assertTrue(ok, reason)
        self.assertEqual(evidence, [{"kind": "changed_file", "value": "tracked.txt"}])

    def test_path_outside_workspace_is_rejected(self):
        ok, evidence, _ = verify_work_evidence(
            str(self.repo),
            [{"kind": "changed_file", "value": "../outside.txt"}],
        )
        self.assertFalse(ok)
        self.assertEqual(evidence, [])


if __name__ == "__main__":
    unittest.main()
