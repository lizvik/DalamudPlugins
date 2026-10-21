import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import generate_repo as repo


def manifest(**overrides):
    value = {
        "Author": "Example Author",
        "Name": "Example Plugin",
        "InternalName": "ExamplePlugin",
        "AssemblyVersion": "1.2.3.0",
        "Description": "示例插件",
        "DalamudApiLevel": 1,  # A fixture, not a current API recommendation.
    }
    value.update(overrides)
    return value


def config(**overrides):
    value = {
        "enabled": True,
        "repository": "example/ExamplePlugin",
        "internal_name": "ExamplePlugin",
        "release_tag": "latest",
        "zip_asset": "latest.zip",
    }
    value.update(overrides)
    return value


def package(value=None, dll=True, extra=None):
    stream = io.BytesIO()
    with ZipFile(stream, "w") as archive:
        archive.writestr("ExamplePlugin.json", json.dumps(manifest() if value is None else value))
        if dll:
            archive.writestr("ExamplePlugin.dll", b"fixture-not-a-real-DLL")
        if extra:
            archive.writestr(extra, b"extra")
    return stream.getvalue()


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

    def test_disabled_placeholders_need_no_network(self):
        self.write_config(config(enabled=False, repository="YOUR_GITHUB_USERNAME/PluginA"))
        with patch.object(repo, "fetch", side_effect=AssertionError("Network must not be used")):
            self.assertEqual(repo.generate(self.config_file, self.output), 0)
        self.assertEqual(self.output.read_text(), "[]\n")

    def test_enabled_placeholder_is_rejected(self):
        self.write_config(config(repository="YOUR_GITHUB_USERNAME/PluginA"))
        with self.assertRaisesRegex(repo.RepoError, "replace YOUR_GITHUB_USERNAME"):
            repo.load_configs(self.config_file)

    def test_duplicate_names_are_rejected(self):
        self.write_config()
        self.write_config(config(internal_name="exampleplugin"))
        with self.assertRaisesRegex(repo.RepoError, "duplicate"):
            repo.load_configs(self.config_file)

    def test_unknown_config_key_is_rejected(self):
        self.write_config(config(zip_assset="typo.zip"))
        with self.assertRaisesRegex(repo.RepoError, "unknown keys"):
            repo.load_configs(self.config_file)

    def test_missing_source_file_does_not_clear_feed(self):
        self.config_file.unlink()
        previous = b'[{"InternalName":"ExistingPlugin"}]\n'
        self.output.write_bytes(previous)
        with self.assertRaisesRegex(repo.RepoError, "Configuration file does not exist"):
            repo.generate(self.config_file, self.output)
        self.assertEqual(self.output.read_bytes(), previous)

    def test_source_file_requires_array(self):
        self.config_file.write_text(json.dumps(config()), encoding="utf-8")
        with self.assertRaisesRegex(repo.RepoError, "must be an array"):
            repo.load_configs(self.config_file)

    def test_invalid_source_entry_reports_index(self):
        self.config_file.write_text(json.dumps([config(), "invalid"]), encoding="utf-8")
        with self.assertRaisesRegex(repo.RepoError, r"plugins\.json\[1\]: plugin configuration must be an object"):
            repo.load_configs(self.config_file)

    def test_multiple_sources_generate_sorted_feed_and_skip_disabled(self):
        self.write_config(config(internal_name="ZPlugin"))
        self.write_config(config(internal_name="DisabledPlugin", enabled=False))
        self.write_config(config(internal_name="APlugin"))
        with patch.object(repo, "build_entry", side_effect=lambda cfg: manifest(InternalName=cfg["internal_name"])) as build:
            self.assertEqual(repo.generate(self.config_file, self.output), 2)
        self.assertEqual([call.args[0]["internal_name"] for call in build.call_args_list], ["ZPlugin", "APlugin"])
        self.assertEqual([entry["InternalName"] for entry in json.loads(self.output.read_bytes())], ["APlugin", "ZPlugin"])

    def test_cli_accepts_custom_source_file(self):
        self.write_config()
        with patch.object(sys, "argv", ["generate_repo.py", "--config", str(self.config_file), "--validate-config"]), \
             patch.object(repo, "fetch", side_effect=AssertionError("Validation must be offline")):
            self.assertEqual(repo.main(), 0)

    def test_valid_package(self):
        self.assertEqual(repo.read_package(package(), "ExamplePlugin"), manifest())

    def test_package_requires_root_dll(self):
        with self.assertRaisesRegex(repo.RepoError, "ExamplePlugin.dll"):
            repo.read_package(package(dll=False), "ExamplePlugin")

    def test_zip_traversal_is_rejected(self):
        with self.assertRaisesRegex(repo.RepoError, "unsafe path"):
            repo.read_package(package(extra="../outside.txt"), "ExamplePlugin")

    def test_invalid_zip_is_rejected(self):
        with self.assertRaisesRegex(repo.RepoError, "ZIP"):
            repo.read_package(b"not-a-zip", "ExamplePlugin")

    def test_manifest_validation(self):
        for invalid in (
            manifest(InternalName="WrongName"),
            manifest(AssemblyVersion="v1.2.3"),
            manifest(DalamudApiLevel=True),
            manifest(DalamudApiLevel=0),
            manifest(IsTestingExclusive=True),
            manifest(Tags="wrong"),
        ):
            with self.subTest(invalid=invalid), self.assertRaises(repo.RepoError):
                repo.validate_manifest(invalid, "ExamplePlugin")

    def release(self, **overrides):
        base = "https://github.com/example/ExamplePlugin/releases/download/v1.2.3/"
        value = {
            "tag_name": "v1.2.3", "draft": False, "prerelease": False,
            "published_at": "2026-01-01T00:00:00Z",
            "assets": [
                {"name": "latest.zip", "browser_download_url": base + "latest.zip"},
                {"name": "ExamplePlugin.json", "browser_download_url": base + "ExamplePlugin.json"},
            ],
        }
        value.update(overrides)
        return value

    def test_release_to_feed_end_to_end_and_repeat_is_unchanged(self):
        self.write_config()
        release = self.release()
        bundled = manifest(TestingAssemblyVersion="9.9.0.0", DownloadLinkTesting="old", IsTestingExclusive=False)
        def fetch_fixture(url, limit):
            if url == "https://api.github.com/repos/example/ExamplePlugin/releases/latest":
                return json.dumps(release).encode()
            self.assertEqual(url, release["assets"][0]["browser_download_url"])
            return package(bundled)
        with patch.object(repo, "fetch", side_effect=fetch_fixture):
            self.assertEqual(repo.generate(self.config_file, self.output), 1)
            entry = json.loads(self.output.read_bytes())[0]
            self.assertEqual(entry["AssemblyVersion"], "1.2.3.0")
            self.assertEqual(entry["DownloadLinkInstall"], release["assets"][0]["browser_download_url"])
            self.assertEqual(entry["DownloadLinkInstall"], entry["DownloadLinkUpdate"])
            self.assertEqual(entry["LastUpdate"], 1767225600)
            self.assertNotIn("TestingAssemblyVersion", entry)
            self.assertNotIn("DownloadLinkTesting", entry)
            with patch.object(repo.os, "replace", side_effect=AssertionError("Should not rewrite")):
                repo.generate(self.config_file, self.output)

    def test_prerelease_is_rejected(self):
        with patch.object(repo, "fetch", return_value=json.dumps(self.release(prerelease=True)).encode()):
            with self.assertRaisesRegex(repo.RepoError, "stable"):
                repo.build_entry(config())

    def test_pinned_tag_uses_tag_endpoint(self):
        with patch.object(repo, "fetch", side_effect=[json.dumps(self.release()).encode(), package()]) as fetch:
            repo.build_entry(config(release_tag="v1.2.3"))
        self.assertEqual(fetch.call_args_list[0].args[0], "https://api.github.com/repos/example/ExamplePlugin/releases/tags/v1.2.3")

    def test_external_manifest_must_match_package(self):
        with patch.object(repo, "fetch", side_effect=[
            json.dumps(self.release()).encode(), package(),
            json.dumps(manifest(AssemblyVersion="2.0.0.0")).encode(),
        ]):
            with self.assertRaisesRegex(repo.RepoError, "disagree"):
                repo.build_entry(config(manifest_asset="ExamplePlugin.json"))

    def test_missing_release_asset_is_rejected(self):
        with self.assertRaisesRegex(repo.RepoError, "exactly one asset"):
            repo.release_asset(self.release(), "missing.zip", "example/ExamplePlugin")

    def test_floating_download_url_is_rejected(self):
        release = self.release()
        release["assets"][0]["browser_download_url"] = "https://github.com/example/ExamplePlugin/releases/latest/download/latest.zip"
        with self.assertRaisesRegex(repo.RepoError, "Unexpected download URL"):
            repo.release_asset(release, "latest.zip", "example/ExamplePlugin")

    def test_later_failure_preserves_entire_existing_feed(self):
        self.write_config()
        self.write_config(config(internal_name="AnotherPlugin"))
        previous = b'[{"InternalName": "OldPlugin"}]\n'
        self.output.write_bytes(previous)
        with patch.object(repo, "build_entry", side_effect=[manifest(), repo.RepoError("Release unavailable")]):
            with self.assertRaisesRegex(repo.RepoError, "unavailable"):
                repo.generate(self.config_file, self.output)
        self.assertEqual(self.output.read_bytes(), previous)
        self.assertEqual(list(self.root.glob("*.tmp")), [])

    def test_populated_feed_cannot_be_accidentally_emptied(self):
        self.output.write_text('[{"InternalName":"OldPlugin"}]', encoding="utf-8")
        with self.assertRaisesRegex(repo.RepoError, "Refusing to clear"):
            repo.generate(self.config_file, self.output)
        repo.generate(self.config_file, self.output, allow_empty=True)
        self.assertEqual(json.loads(self.output.read_bytes()), [])

    def test_failed_atomic_replace_preserves_output(self):
        self.write_config()
        self.output.write_bytes(b"[]\n")
        with patch.object(repo, "build_entry", return_value=manifest()), \
             patch.object(repo.os, "replace", side_effect=OSError("Cannot replace")):
            with self.assertRaises(OSError):
                repo.generate(self.config_file, self.output)
        self.assertEqual(self.output.read_bytes(), b"[]\n")
        self.assertEqual(list(self.root.glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
