"""Tests for the configuration store (stdlib only, no FastAPI needed)."""

import json

from app import store

CONFIG = {
    "ewelink": {
        "username": "me@example.com",
        "password": "secret",
        "country_code": "+34",
    },
    "mqtt": {
        "host": "core-mosquitto",
        "port": 1884,
        "username": "mqtt",
        "password": "broker-secret",
        "tls": True,
        "prefix": "/home/",
        "retain": False,
    },
}


def test_defaults(monkeypatch, tmp_path):
    monkeypatch.setenv("CONFIG_PATH", str(tmp_path / "config.json"))

    config = store.load_config()

    assert config["ewelink"] == {"username": "", "password": "", "country_code": ""}
    assert config["mqtt"]["port"] == 1883
    assert config["mqtt"]["prefix"] == "sonoff"
    assert store.is_complete(config) is False


def test_save_and_load(monkeypatch, tmp_path):
    path = tmp_path / "config.json"
    monkeypatch.setenv("CONFIG_PATH", str(path))

    saved = store.save_config(CONFIG)

    assert saved == path
    assert path.exists()
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["ewelink"]["password"] == "secret"

    loaded = store.load_config()
    assert loaded["ewelink"]["username"] == "me@example.com"
    assert loaded["mqtt"]["host"] == "core-mosquitto"
    assert loaded["mqtt"]["prefix"] == "home"  # normalised


def test_invalid_json_falls_back_to_defaults(monkeypatch, tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{not json", encoding="utf-8")
    monkeypatch.setenv("CONFIG_PATH", str(path))

    config = store.load_config()

    assert config["mqtt"]["host"] == ""


def test_masked_hides_passwords(monkeypatch):
    view = store.masked(CONFIG)

    assert view["ewelink"]["password"] == ""
    assert view["ewelink"]["has_password"] is True
    assert view["mqtt"]["password"] == ""
    assert view["mqtt"]["has_password"] is True
    assert view["ewelink"]["username"] == "me@example.com"


def test_merge_secrets_keeps_saved_passwords():
    incoming = {
        "ewelink": {"username": "me@example.com", "password": ""},
        "mqtt": {"host": "core-mosquitto", "password": ""},
    }

    merged = store.merge_secrets(incoming, CONFIG)

    assert merged["ewelink"]["password"] == "secret"
    assert merged["mqtt"]["password"] == "broker-secret"


def test_is_complete():
    assert store.is_complete(CONFIG) is True
    assert store.is_complete(store._normalize({"ewelink": {"username": "x"}})) is False
