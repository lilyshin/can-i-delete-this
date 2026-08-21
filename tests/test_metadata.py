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

    def test_version_agrees_across_both_plugin_files(self):
        # M6: plugin.json's own version, marketplace.json's top-level
        # metadata.version, and marketplace.json's per-plugin entry
        # version are three separate strings a release step has to keep
        # in step by hand; nothing caught a skew between them before this.
        plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())
        marketplace = json.loads(
            (ROOT / ".claude-plugin" / "marketplace.json").read_text())
        plugin_entry = next(p for p in marketplace["plugins"] if p["name"] == NAME)
        versions = {
            "plugin.json": plugin["version"],
            "marketplace.json metadata.version": marketplace["metadata"]["version"],
            "marketplace.json plugins[].version": plugin_entry["version"],
        }
        self.assertEqual(
            len(set(versions.values())), 1,
            "version mismatch across plugin metadata: {}".format(versions))

    def test_skill_frontmatter_has_name_and_description_only(self):
        text = (ROOT / "skills" / NAME / "SKILL.md").read_text()
        self.assertTrue(text.startswith("---\n"))
        block = text.split("---\n")[1]
        keys = [l.split(":")[0] for l in block.splitlines() if l and not l.startswith(" ")]
        self.assertEqual(sorted(keys), ["description", "name"])

    def test_plugin_json_declares_the_check_command(self):
        data = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())
        self.assertIn("commands", data)
        self.assertIn("./commands/check.md", data["commands"])

    def test_check_command_file_exists_and_parses(self):
        path = ROOT / "commands" / "check.md"
        self.assertTrue(path.is_file())
        text = path.read_text()
        self.assertTrue(text.startswith("---\n"))
        parts = text.split("---\n")
        # ["", frontmatter, body...]
        self.assertGreaterEqual(len(parts), 3)
        frontmatter = parts[1]
        fields = {}
        for line in frontmatter.splitlines():
            if not line or line.startswith(" "):
                continue
            key, _, value = line.partition(":")
            fields[key.strip()] = value.strip()
        self.assertIn("description", fields)
        self.assertTrue(fields["description"])
        self.assertIn("allowed-tools", fields)
        tools = [t.strip() for t in fields["allowed-tools"].split(",")]
        self.assertIn("Skill", tools)
        # Read-only: no tool that writes to the user's files.
        self.assertNotIn("Edit", tools)
        self.assertNotIn("Write", tools)

    def test_check_command_references_arguments_and_skill(self):
        text = (ROOT / "commands" / "check.md").read_text()
        self.assertIn("$ARGUMENTS", text)
        self.assertIn(NAME, text)


if __name__ == "__main__":
    unittest.main()
