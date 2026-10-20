"""Configuration persistence for the OpenSonoffMQTT stand-alone app."""

import json
import logging
import os
from pathlib import Path

_LOGGER = logging.getLogger(__name__)

DEFAULT_PATH = Path("/data/config.json")
FALLBACK_PATH = Path("data/config.json")

DEFAULT_CONFIG = {
    "ewelink": {"username": "", "password": "", "country_code": ""},
    "mqtt": {
        "host": "",
        "port": 1883,
        "username": "",
        "password": "",
        "tls": False,
        "prefix": "sonoff",
        "retain": True,
        "discovery": True,
        "discovery_prefix": "homeassistant",
    },
}


def config_path() -> Path:
    return Path(os.environ.get("CONFIG_PATH") or DEFAULT_PATH)


def _normalize(raw: dict | None) -> dict:
    """Merge a stored/partial config over the defaults, keeping known types."""
    config = {
        "ewelink": dict(DEFAULT_CONFIG["ewelink"]),
        "mqtt": dict(DEFAULT_CONFIG["mqtt"]),
    }
    for section in ("ewelink", "mqtt"):
        for key, value in ((raw or {}).get(section) or {}).items():
            if key in config[section] and value is not None:
                config[section][key] = value

    config["mqtt"]["port"] = int(config["mqtt"]["port"] or 1883)
    config["mqtt"]["tls"] = bool(config["mqtt"]["tls"])
    config["mqtt"]["retain"] = bool(config["mqtt"]["retain"])
    config["mqtt"]["prefix"] = str(config["mqtt"]["prefix"] or "sonoff").strip("/")
    config["mqtt"]["discovery"] = bool(config["mqtt"]["discovery"])
    config["mqtt"]["discovery_prefix"] = str(
        config["mqtt"]["discovery_prefix"] or "homeassistant"
    ).strip("/")
    return config


def load_config() -> dict:
    path = config_path()
    try:
        with path.open(encoding="utf-8") as file:
            return _normalize(json.load(file))
    except FileNotFoundError:
        return _normalize(None)
    except (OSError, ValueError) as error:
        _LOGGER.warning("Can't read config %s: %s", path, error)
        return _normalize(None)


def save_config(config: dict) -> Path:
    """Save the config; fall back to a local folder when /data is not writable."""
    config = _normalize(config)
    for path in (config_path(), FALLBACK_PATH):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            with tmp.open("w", encoding="utf-8") as file:
                json.dump(config, file, indent=2)
            os.chmod(tmp, 0o600)
            tmp.replace(path)
            return path
        except OSError as error:
            _LOGGER.warning("Can't save config to %s: %s", path, error)
    raise OSError("Can't save the configuration")


def is_complete(config: dict) -> bool:
    ewelink = config.get("ewelink") or {}
    mqtt = config.get("mqtt") or {}
    return bool(
        ewelink.get("username") and ewelink.get("password") and mqtt.get("host")
    )


def merge_secrets(new: dict, old: dict) -> dict:
    """Keep the stored passwords when the UI sends an empty one."""
    new = _normalize(new)
    old = _normalize(old)
    for section, key in (("ewelink", "password"), ("mqtt", "password")):
        if not new[section].get(key) and old[section].get(key):
            new[section][key] = old[section][key]
    return new


def masked(config: dict) -> dict:
    """Public view of the config: never send the passwords to the browser."""
    config = _normalize(config)
    view = json.loads(json.dumps(config))
    for section, key in (("ewelink", "password"), ("mqtt", "password")):
        value = view[section].get(key) or ""
        view[section][key] = ""
        view[section][f"has_{key}"] = bool(value)
    return view
