import base64
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import generate_repo as repo


def manifest(**overrides):
    value = {
        "Author": "Example Author", "Name": "Example Plugin",
        "InternalName": "ExamplePlugin", "AssemblyVersion": "1.2.3.0",
        "Description": "示例插件", "DalamudApiLevel": 1,
        "DownloadLinkInstall": "https://example.com/plugin.zip",
        "DownloadLinkUpdate": "https://example.com/plugin.zip",
        "LastUpdate": 1767225600,
    }
    value.update(overrides)
    return value


def config(**overrides):
    value = {"enabled": True, "repository": "example/ExamplePlugin", "internal_name": "ExamplePlugin"}
    value.update(overrides)
    return value


def github_file(value):
    return json.dumps({"encoding": "base64", "content": base64.b64encode(json.dumps(value).encode()).decode()}).encode()


class GeneratorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config_file = self.root / "plugins.json"
        self.config_file.write_text("[]\n", encoding="utf-8")
        self.output = self.root / "pluginmaster.json"

    def write_config(self, value=None):
        sources = json.loads(self.config_file.read_text(encoding="utf-8"))
        sources.append(config() if value is None else value)
        self.config_file.write_text(json.dumps(sources), encoding="utf-8")

    def test_disabled_placeholder_needs_no_network(self):
        self.write_config(config(enabled=False, repository="YOUR_GITHUB_USERNAME/PluginA"))
        with patch.object(repo, "fetch", side_effect=AssertionError("Network must not be used")):
            self.assertEqual(repo.generate(self.config_file, self.output), 0)

    def test_config_rejects_old_release_fields(self):
        self.write_config(config(zip_asset="old.zip"))
        with self.assertRaisesRegex(repo.RepoError, "unknown keys"):
            repo.load_configs(self.config_file)

    def test_duplicate_names_are_rejected(self):
        self.write_config()
        self.write_config(config(internal_name="exampleplugin"))
        with self.assertRaisesRegex(repo.RepoError, "duplicate"):
            repo.load_configs(self.config_file)

    def test_only_repository_repo_json_is_fetched_without_version_check(self):
        self.write_config()
        source = manifest(AssemblyVersion="v1.2.3", TestingAssemblyVersion="old")
        with patch.object(repo, "fetch", return_value=github_file([source])) as fetch:
            self.assertEqual(repo.generate(self.config_file, self.output), 1)
        fetch.assert_called_once_with("https://api.github.com/repos/example/ExamplePlugin/contents/repo.json", repo.MAX_JSON)
        entry = json.loads(self.output.read_bytes())[0]
        self.assertEqual(entry["AssemblyVersion"], "v1.2.3")
        self.assertEqual(entry["DownloadLinkInstall"], source["DownloadLinkInstall"])
        self.assertNotIn("TestingAssemblyVersion", entry)

    def test_repo_json_can_be_single_object(self):
        with patch.object(repo, "fetch", return_value=github_file(manifest())):
            self.assertEqual(repo.build_entry(config())["InternalName"], "ExamplePlugin")

    def test_repo_json_must_contain_exactly_one_matching_plugin(self):
        for source in ([], [manifest(), manifest()], [manifest(InternalName="OtherPlugin")]):
            with self.subTest(source=source), patch.object(repo, "fetch", return_value=github_file(source)):
                with self.assertRaisesRegex(repo.RepoError, "exactly one"):
                    repo.build_entry(config())

    def test_missing_download_link_is_rejected(self):
        with patch.object(repo, "fetch", return_value=github_file(manifest(DownloadLinkInstall=""))):
            with self.assertRaisesRegex(repo.RepoError, "DownloadLinkInstall"):
                repo.build_entry(config())

    def test_invalid_api_level_is_rejected(self):
        with patch.object(repo, "fetch", return_value=github_file(manifest(DalamudApiLevel=0))):
            with self.assertRaisesRegex(repo.RepoError, "DalamudApiLevel"):
                repo.build_entry(config())

    def test_later_failure_preserves_feed(self):
        self.write_config()
        self.write_config(config(internal_name="AnotherPlugin"))
        previous = b'[{"InternalName": "OldPlugin"}]\n'
        self.output.write_bytes(previous)
        with patch.object(repo, "build_entry", side_effect=[manifest(), repo.RepoError("Unavailable")]):
            with self.assertRaisesRegex(repo.RepoError, "Unavailable"):
                repo.generate(self.config_file, self.output)
        self.assertEqual(self.output.read_bytes(), previous)

    def test_populated_feed_cannot_be_accidentally_emptied(self):
        self.output.write_text('[{"InternalName":"OldPlugin"}]', encoding="utf-8")
        with self.assertRaisesRegex(repo.RepoError, "Refusing to clear"):
            repo.generate(self.config_file, self.output)
        repo.generate(self.config_file, self.output, allow_empty=True)
        self.assertEqual(json.loads(self.output.read_bytes()), [])


if __name__ == "__main__":
    unittest.main()
