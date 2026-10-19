#!/usr/bin/env python3
"""Fail when the git tag does not match the integration manifest version."""

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: check_release.py vX.Y.Z")
        return 2

    tag = sys.argv[1].lstrip("v")
    manifest = json.loads(
        (ROOT / "custom_components/sonoff/manifest.json").read_text(encoding="utf-8")
    )

    if manifest["version"] != tag:
        print(
            f"ERROR: manifest version {manifest['version']} != tag {tag}. "
            "Bump custom_components/sonoff/manifest.json before tagging."
        )
        return 1

    print(f"Release {tag} matches the manifest version")
    return 0


if __name__ == "__main__":
    sys.exit(main())
