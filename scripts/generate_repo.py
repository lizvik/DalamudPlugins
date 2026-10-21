#!/usr/bin/env python3
"""Build a Dalamud repository from public GitHub release assets (stdlib only)."""

from __future__ import annotations

import argparse
from datetime import datetime
import io
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from zipfile import BadZipFile, ZipFile

ROOT = Path(__file__).resolve().parents[1]
MAX_JSON = 1024 * 1024
MAX_ZIP = 128 * 1024 * 1024
MAX_UNPACKED = 512 * 1024 * 1024
NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*")
VERSION = re.compile(r"\d+\.\d+(?:\.\d+){0,2}", re.ASCII)
CONFIG_KEYS = {"enabled", "repository", "internal_name", "release_tag", "zip_asset", "manifest_asset"}


class RepoError(Exception):
    """A configuration, release or manifest is unsuitable for publication."""


class SafeRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlsplit(newurl).scheme != "https":
            raise RepoError("Download redirected to a non-HTTPS address")
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None:
            redirected.remove_header("Authorization")
        return redirected


def fetch(url: str, limit: int) -> bytes:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise RepoError("Download address must be an HTTPS URL without credentials")
    headers = {"User-Agent": "dalamud-plugin-repository", "Accept": "application/octet-stream"}
    if parsed.hostname == "api.github.com":
        headers["Accept"] = "application/vnd.github+json"
        token = os.environ.get("GITHUB_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
    try:
        with build_opener(SafeRedirect()).open(Request(url, headers=headers), timeout=30) as response:
            result = response.read(limit + 1)
    except HTTPError as exc:
        raise RepoError(f"HTTP {exc.code} from {parsed.hostname}; check public releases, asset names and API limits") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise RepoError(f"Network request failed for {parsed.hostname}: {exc}") from exc
    if len(result) > limit:
        raise RepoError(f"Download exceeds the {limit} byte limit")
    return result


def parse_json(data: bytes, label: str):
    try:
        return json.loads(data.decode("utf-8-sig"))
    except (UnicodeError, ValueError) as exc:
        raise RepoError(f"{label}: invalid UTF-8 JSON") from exc


def nonempty(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def load_configs(path: Path) -> list[dict]:
    if not path.is_file():
        raise RepoError(f"Configuration file does not exist: {path}")
    sources = parse_json(path.read_bytes(), path.name)
    if not isinstance(sources, list):
        raise RepoError(f"{path.name}: configuration must be an array of plugin objects")
    configs = []
    names = set()
    for index, cfg in enumerate(sources):
        label = f"{path.name}[{index}]"
        if not isinstance(cfg, dict):
            raise RepoError(f"{label}: plugin configuration must be an object")
        if set(cfg) - CONFIG_KEYS:
            raise RepoError(f"{label}: unknown keys: {sorted(set(cfg) - CONFIG_KEYS)}")
        if type(cfg.get("enabled")) is not bool:
            raise RepoError(f"{label}: enabled must be true or false")
        for field in ("repository", "internal_name", "release_tag", "zip_asset"):
            if not nonempty(cfg.get(field)):
                raise RepoError(f"{label}: {field} must be a non-empty string")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", cfg["repository"]):
            raise RepoError(f"{label}: repository must be owner/repo")
        if not NAME.fullmatch(cfg["internal_name"]):
            raise RepoError(f"{label}: invalid internal_name")
        for field in ("zip_asset", "manifest_asset"):
            if field in cfg and (not nonempty(cfg[field]) or "/" in cfg[field] or "\\" in cfg[field]):
                raise RepoError(f"{label}: {field} must be an exact asset filename")
        if not cfg["zip_asset"].lower().endswith(".zip"):
            raise RepoError(f"{label}: zip_asset must end in .zip")
        if not cfg["enabled"]:
            continue
        if "YOUR_GITHUB_USERNAME" in cfg["repository"]:
            raise RepoError(f"{label}: replace YOUR_GITHUB_USERNAME before enabling")
        key = cfg["internal_name"].casefold()
        if key in names:
            raise RepoError(f"{label}: duplicate InternalName: {cfg['internal_name']}")
        names.add(key)
        configs.append(cfg)
    return configs


def validate_manifest(manifest, expected_name: str) -> None:
    if not isinstance(manifest, dict):
        raise RepoError("Manifest must be an object")
    for field in ("Author", "Name", "InternalName", "AssemblyVersion", "Description"):
        if not nonempty(manifest.get(field)):
            raise RepoError(f"Manifest requires a non-empty {field}")
    if manifest["InternalName"] != expected_name:
        raise RepoError(f"InternalName mismatch: expected {expected_name}")
    version = manifest["AssemblyVersion"]
    if not VERSION.fullmatch(version) or any(int(part) > 2147483647 for part in version.split(".")):
        raise RepoError("AssemblyVersion must be a numeric .NET version, e.g. 1.2.3.0")
    if type(manifest.get("DalamudApiLevel")) is not int or manifest["DalamudApiLevel"] < 1:
        raise RepoError("DalamudApiLevel must be a positive integer from the plugin build")
    if "ApplicableVersion" in manifest and not nonempty(manifest["ApplicableVersion"]):
        raise RepoError("ApplicableVersion must be a non-empty string")
    if "Tags" in manifest and (not isinstance(manifest["Tags"], list) or
                               not all(nonempty(tag) for tag in manifest["Tags"])):
        raise RepoError("Tags must be an array of non-empty strings")
    if manifest.get("IsTestingExclusive") not in (None, False, "False", "false"):
        raise RepoError("Testing-exclusive plugins cannot be published to this stable feed")


def read_package(data: bytes, internal_name: str) -> dict:
    try:
        with ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
            filenames = [entry.filename for entry in infos]
            if len(filenames) != len(set(filenames)):
                raise RepoError("ZIP contains duplicate filenames")
            if sum(entry.file_size for entry in infos) > MAX_UNPACKED:
                raise RepoError("ZIP exceeds the uncompressed size limit")
            for filename in filenames:
                normalized = filename.replace("\\", "/")
                if normalized.startswith("/") or ":" in normalized or ".." in normalized.split("/"):
                    raise RepoError("ZIP contains an unsafe path")
            for filename in (f"{internal_name}.dll", f"{internal_name}.json"):
                if filename not in filenames or archive.getinfo(filename).file_size == 0:
                    raise RepoError(f"ZIP must contain a non-empty {filename} at its root")
            manifest_info = archive.getinfo(f"{internal_name}.json")
            if manifest_info.file_size > MAX_JSON:
                raise RepoError("Packaged manifest is too large")
            corrupt = archive.testzip()
            if corrupt:
                raise RepoError(f"ZIP checksum failed: {corrupt}")
            manifest = parse_json(archive.read(manifest_info), "Packaged manifest")
    except (BadZipFile, RuntimeError, NotImplementedError, EOFError) as exc:
        raise RepoError(f"Invalid or unsupported ZIP: {exc}") from exc
    validate_manifest(manifest, internal_name)
    return manifest


def release_asset(release: dict, name: str, repository: str) -> str:
    assets = release.get("assets", [])
    if not isinstance(assets, list):
        raise RepoError("Release assets must be an array")
    matches = [asset for asset in assets if isinstance(asset, dict) and asset.get("name") == name]
    if len(matches) != 1:
        raise RepoError(f"Release must contain exactly one asset named {name}")
    url = matches[0].get("browser_download_url")
    # Only immutable-by-tag, public download URLs for this release are accepted.
    tag = quote(release["tag_name"], safe="")
    expected = f"https://github.com/{repository}/releases/download/{tag}/{quote(name, safe='')}"
    if url != expected:
        raise RepoError(f"Unexpected download URL for {name}; use a public GitHub release asset")
    return url


def build_entry(cfg: dict) -> dict:
    repository = cfg["repository"]
    selector = "latest" if cfg["release_tag"] == "latest" else "tags/" + quote(cfg["release_tag"], safe="")
    release = parse_json(fetch(f"https://api.github.com/repos/{repository}/releases/{selector}", MAX_JSON), "GitHub release")
    if not isinstance(release, dict) or not nonempty(release.get("tag_name")):
        raise RepoError(f"{repository}: invalid release response")
    if release.get("draft") is not False or release.get("prerelease") is not False:
        raise RepoError(f"{repository}: only published stable releases are supported")
    download_url = release_asset(release, cfg["zip_asset"], repository)
    manifest = read_package(fetch(download_url, MAX_ZIP), cfg["internal_name"])
    if "manifest_asset" in cfg:
        external_url = release_asset(release, cfg["manifest_asset"], repository)
        external = parse_json(fetch(external_url, MAX_JSON), "Release manifest")
        validate_manifest(external, cfg["internal_name"])
        for field in ("InternalName", "AssemblyVersion", "DalamudApiLevel"):
            if external[field] != manifest[field]:
                raise RepoError(f"Release manifest and packaged manifest disagree on {field}")
        manifest = external
    try:
        published = datetime.fromisoformat(release["published_at"].replace("Z", "+00:00"))
        if published.tzinfo is None:
            raise ValueError("Missing timezone")
        timestamp = int(published.timestamp())
    except (KeyError, AttributeError, TypeError, ValueError, OverflowError) as exc:
        raise RepoError("Release has no valid published_at timestamp") from exc
    # Remove testing data inherited from an upstream manifest.
    entry = {key: value for key, value in manifest.items()
             if not key.startswith("Testing") and key not in ("DownloadLinkTesting", "IsTestingExclusive")}
    entry.setdefault("ApplicableVersion", "any")
    entry.setdefault("RepoUrl", f"https://github.com/{repository}")
    entry.update(DownloadLinkInstall=download_url, DownloadLinkUpdate=download_url, LastUpdate=timestamp)
    return entry


def generate(config_file: Path, output: Path, allow_empty: bool = False) -> int:
    configs = load_configs(config_file)
    # Resolve everything before touching the current feed.
    entries = []
    for cfg in configs:
        print(f"Resolving {cfg['internal_name']} ({cfg['repository']})", flush=True)
        entries.append(build_entry(cfg))
    entries.sort(key=lambda entry: entry["InternalName"].casefold())
    if not entries and not allow_empty and output.exists():
        existing = parse_json(output.read_bytes(), str(output))
        if existing != []:
            raise RepoError("Refusing to clear a populated feed; use --allow-empty for intentional removal")
    content = (json.dumps(entries, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    if output.exists() and output.read_bytes() == content:
        print(f"Unchanged: {output} ({len(entries)} plugins)")
        return len(entries)
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(dir=output.parent, suffix=".tmp", delete=False) as stream:
            tmp_path = Path(stream.name)
            stream.write(content)
        os.replace(tmp_path, output)
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
    print(f"Generated: {output} ({len(entries)} plugins)")
    return len(entries)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "plugins.json", help="JSON file containing an array of plugin sources")
    parser.add_argument("--output", type=Path, default=ROOT / "pluginmaster.json")
    parser.add_argument("--validate-config", action="store_true", help="Validate local configuration without network access")
    parser.add_argument("--allow-empty", action="store_true", help="Allow intentionally clearing a populated feed")
    args = parser.parse_args()
    try:
        if args.validate_config:
            configs = load_configs(args.config)
            print(f"Configuration valid: {len(configs)} enabled plugins")
        else:
            generate(args.config, args.output, args.allow_empty)
    except (RepoError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
