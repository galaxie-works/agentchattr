"""Tests for opt-in project members and their native teammate relays."""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from projects import ProjectCatalog, materialize_projects


class ProjectCatalogTests(unittest.TestCase):
    def setUp(self):
        self.base_agents = {
            "codex": {"command": "codex", "cwd": "..", "color": "#10a37f"},
            "claude": {"command": "claude", "cwd": "..", "color": "#da7756"},
        }

    def test_materializes_isolated_members_and_relays(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = {
                "agents": dict(self.base_agents),
                "projects": {
                    "demo": {
                        "path": "workspace",
                        "label": "Demo App",
                        "members": {
                            "codex": {"teammate": "reviewer"},
                            "claude": {},
                        },
                    },
                },
            }
            catalog = materialize_projects(config, root)

        self.assertEqual(catalog.projects[0].path, (root / "workspace").resolve())
        self.assertEqual(config["agents"]["codex-demo"]["provider"], "codex")
        self.assertEqual(config["agents"]["codex-demo"]["cwd"], str((root / "workspace").resolve()))
        self.assertEqual(config["agents"]["codex-demo"]["label"], "Codex · Demo App")
        self.assertEqual(config["agents"]["claude-demo"]["provider"], "claude")
        self.assertEqual(config["relays"]["demo-codex"], {
            "agent": "codex-demo", "teammate": "reviewer", "project": "demo"
        })
        self.assertNotIn("demo-claude", config["relays"])

    def test_rejects_member_without_a_configured_provider(self):
        with self.assertRaisesRegex(ValueError, "no matching"):
            ProjectCatalog.from_config(
                {"demo": {"path": ".", "members": {"missing": {}}}},
                self.base_agents,
                ROOT,
            )

    def test_rejects_generated_relay_that_conflicts_with_an_agent(self):
        with self.assertRaisesRegex(ValueError, "conflicts"):
            ProjectCatalog.from_config(
                {"demo": {"path": ".", "members": {"codex": {"teammate": "reviewer", "relay_alias": "claude"}}}},
                self.base_agents,
                ROOT,
            )


if __name__ == "__main__":
    unittest.main()
