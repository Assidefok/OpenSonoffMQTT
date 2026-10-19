"""Tests for the MQTT topic/payload contract shared with the integration."""

import json

from app.mqtt_bridge import MQTTBridge, clean_prefix


def test_clean_prefix():
    assert clean_prefix(None) == "sonoff"
    assert clean_prefix(" /home/ ") == "home"
    assert clean_prefix("bad/#") == "sonoff"


def test_parse_payload_json_object():
    assert MQTTBridge._parse_payload('{"switch": "on"}') == {"switch": "on"}
    assert MQTTBridge._parse_payload('{"brightness": 80}') == {"brightness": 80}


def test_parse_payload_short_commands():
    assert MQTTBridge._parse_payload("ON") == {"switch": "on"}
    assert MQTTBridge._parse_payload("off") == {"switch": "off"}
    assert MQTTBridge._parse_payload("toggle") == {"switch": "toggle"}


def test_parse_payload_invalid():
    assert MQTTBridge._parse_payload("") is None
    assert MQTTBridge._parse_payload("hello world") is None
    assert MQTTBridge._parse_payload("[1, 2]") is None


def test_snapshot_strips_private_keys():
    device = {
        "deviceid": "abc",
        "name": "Lamp",
        "extra": {"uiid": 1},
        "online": True,
        "params": {"switch": "on", "mac": "aa:bb", "ssid": "home", "rssi": -60},
    }

    snapshot = MQTTBridge._snapshot(device)

    assert snapshot["deviceid"] == "abc"
    assert snapshot["name"] == "Lamp"
    assert snapshot["uiid"] == 1
    assert snapshot["online"] is True
    assert "mac" not in snapshot["params"]
    assert "ssid" not in snapshot["params"]
    assert snapshot["params"]["switch"] == "on"
    assert json.dumps(snapshot)  # serialisable


def test_is_online():
    assert MQTTBridge._is_online({"online": True}) is True
    assert MQTTBridge._is_online({"local": True}) is True
    assert MQTTBridge._is_online({}) is False
