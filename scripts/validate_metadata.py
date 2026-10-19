#!/usr/bin/env python3
"""Validate the repository metadata (manifest, translations, add-on files)."""

import json
import pathlib
import re
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
errors = []


def load_json(path: str):
    try:
        return json.loads((ROOT / path).read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - reported below
        errors.append(f"{path}: {exc}")
        return None


def load_yaml(path: str):
    try:
        return yaml.safe_load((ROOT / path).read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - reported below
        errors.append(f"{path}: {exc}")
        return None


manifest = load_json("custom_components/sonoff/manifest.json")
hacs = load_json("hacs.json")
translations = {
    "en": load_json("custom_components/sonoff/translations/en.json"),
    "es": load_json("custom_components/sonoff/translations/es.json"),
}
addon = load_yaml("addon/config.yaml")
repository = load_yaml("repository.yaml")
compose = load_yaml("docker-compose.yml")

if manifest:
    if manifest.get("domain") != "sonoff":
        errors.append("manifest: domain must be 'sonoff'")
    if not re.fullmatch(r"\d+\.\d+\.\d+", str(manifest.get("version", ""))):
        errors.append(f"manifest: invalid version {manifest.get('version')!r}")
    if manifest.get("config_flow") is not True:
        errors.append("manifest: config_flow must be true")
    requirements = " ".join(manifest.get("requirements", []))
    if "paho-mqtt" not in requirements:
        errors.append("manifest: paho-mqtt requirement is missing")

if hacs is not None:
    if not hacs.get("name"):
        errors.append("hacs.json: missing name")
    if not hacs.get("homeassistant"):
        errors.append("hacs.json: missing homeassistant version")

if addon is not None:
    for key in ("name", "version", "slug", "description", "arch"):
        if not addon.get(key):
            errors.append(f"addon/config.yaml: missing {key}")
    if not re.fullmatch(r"\d+\.\d+\.\d+", str(addon.get("version", ""))):
        errors.append(f"addon/config.yaml: invalid version {addon.get('version')!r}")
    if not re.fullmatch(r"[a-z0-9_-]+", str(addon.get("slug", ""))):
        errors.append(f"addon/config.yaml: invalid slug {addon.get('slug')!r}")
    if addon.get("ingress") and not addon.get("ingress_port"):
        errors.append("addon/config.yaml: ingress requires ingress_port")
    if "options" in addon and "schema" not in addon:
        errors.append("addon/config.yaml: options without schema")

if repository is not None:
    for key in ("name", "url", "maintainer"):
        if not repository.get(key):
            errors.append(f"repository.yaml: missing {key}")

if compose is not None and not compose.get("services"):
    errors.append("docker-compose.yml: missing services")

if all(isinstance(item, dict) for item in translations.values()):
    en_options = translations["en"].get("options", {}).get("step", {}).get("init", {})
    en_data = set(en_options.get("data", {}))
    for language, data in translations.items():
        other = data.get("options", {}).get("step", {}).get("init", {}).get("data", {})
        missing = en_data - set(other)
        if missing:
            errors.append(f"translations/{language}.json: missing option keys {sorted(missing)}")

if errors:
    print("Metadata validation failed:")
    for error in errors:
        print(" -", error)
    sys.exit(1)

print("Metadata OK")
