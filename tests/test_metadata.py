import json
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
NAME = "can-i-delete-this"


class TestMetadata(unittest.TestCase):
    def test_marketplace_declares_the_plugin(self):
        data = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())
        self.assertEqual(data["name"], NAME)
        names = [p["name"] for p in data["plugins"]]
        self.assertIn(NAME, names)

    def test_plugin_json_matches_skill_directory(self):
        data = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())
        self.assertEqual(data["name"], NAME)
        self.assertEqual(data["license"], "MIT")
        self.assertTrue((ROOT / "skills" / NAME / "SKILL.md").is_file())

    def test_codex_plugin_reuses_the_same_skills_dir(self):
        data = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text())
        self.assertEqual(data["skills"], "./skills/")
        self.assertIn("displayName", data["interface"])

    def test_skill_frontmatter_has_name_and_description_only(self):
        text = (ROOT / "skills" / NAME / "SKILL.md").read_text()
        self.assertTrue(text.startswith("---\n"))
        block = text.split("---\n")[1]
        keys = [l.split(":")[0] for l in block.splitlines() if l and not l.startswith(" ")]
        self.assertEqual(sorted(keys), ["description", "name"])


if __name__ == "__main__":
    unittest.main()
