"""Auto-Updater module for AI Caption Generator rules.

Silently checks GitHub repository for rule and prompt updates
(grouping_rules.py, grouping_service.py) on launch and safely applies them locally.
Ensures zero-maintenance synchronization across all team editors.
"""

import ast
import json
import os
from pathlib import Path
import tempfile
from typing import Optional, Tuple
import urllib.request

from config import safe_urlopen

GITHUB_OWNER = "hausenvisuals"
GITHUB_REPO = "AI-Text-Generator"
GITHUB_BRANCH = "main"
RAW_BASE_URL = f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}/{GITHUB_BRANCH}/core"

FILES_TO_SYNC = [
    "grouping_rules.py",
    "grouping_service.py",
]


def get_core_dir() -> Path:
    """Returns the local directory containing core python modules."""
    return Path(__file__).parent.resolve()


def get_local_version() -> Tuple[str, dict]:
    """Reads local version.json if present, or returns default 1.0.0."""
    v_file = get_core_dir() / "version.json"
    if v_file.exists():
        try:
            with open(v_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return str(data.get("version", "1.0.0")), data
        except Exception:
            pass
    return "1.0.0", {"version": "1.0.0"}


def check_and_update_rules(timeout_sec: float = 2.0, force: bool = False) -> bool:
    """Checks GitHub for newer rules version and atomically updates local files if available.

    Runs within timeout_sec (default 2s). If offline or unreachable, fails silently
    so the editor's workflow is never interrupted.
    """
    local_version, local_meta = get_local_version()
    core_dir = get_core_dir()

    try:
        # 1. Fetch remote version.json
        version_url = f"{RAW_BASE_URL}/version.json"
        req = urllib.request.Request(
            version_url,
            headers={"User-Agent": "AE-AI-Text-Generator-Updater/1.0"},
        )
        with safe_urlopen(req, timeout=int(max(1, timeout_sec))) as resp:
            remote_raw = resp.read().decode("utf-8")
            remote_meta = json.loads(remote_raw)
            remote_version = str(remote_meta.get("version", ""))

        if not remote_version:
            return False

        # If versions match and not forced, local rules are up to date
        if remote_version == local_version and not force:
            return False

        print(f"[Auto-Updater] New rules detected: v{remote_version} (local: v{local_version}). Syncing from GitHub...")

        # 2. Download and validate each file
        downloaded_contents = {}
        for fname in FILES_TO_SYNC:
            file_url = f"{RAW_BASE_URL}/{fname}"
            f_req = urllib.request.Request(
                file_url,
                headers={"User-Agent": "AE-AI-Text-Generator-Updater/1.0"},
            )
            with safe_urlopen(f_req, timeout=int(max(1, timeout_sec))) as f_resp:
                content = f_resp.read().decode("utf-8")

            # Syntax validation: ensure valid Python syntax (prevents corrupted or HTML 404 pages)
            try:
                ast.parse(content, filename=fname)
            except SyntaxError as syn_err:
                print(f"[Auto-Updater Warning] Remote {fname} failed syntax validation: {syn_err}. Update aborted.")
                return False

            downloaded_contents[fname] = content

        # 3. Apply updates atomically
        for fname, content in downloaded_contents.items():
            dest_file = core_dir / fname
            # Write to temporary file in the same directory, then replace atomically
            temp_file = dest_file.with_suffix(".tmp")
            with open(temp_file, "w", encoding="utf-8") as tf:
                tf.write(content)
            temp_file.replace(dest_file)

        # 4. Save updated local version.json
        v_dest = core_dir / "version.json"
        with open(v_dest, "w", encoding="utf-8") as vf:
            json.dump(remote_meta, vf, indent=2, ensure_ascii=False)

        print(f"[Auto-Updater] ✓ Successfully updated kinetic typography rules to v{remote_version}.")
        return True

    except Exception as e:
        # Silent fallback: offline, timeout, or DNS issue -> proceed with existing local rules
        return False


if __name__ == "__main__":
    import sys
    force_update = "--force" in sys.argv
    updated = check_and_update_rules(timeout_sec=5.0, force=force_update)
    ver, _ = get_local_version()
    print(f"Current local rules version: v{ver} (Updated: {updated})")
