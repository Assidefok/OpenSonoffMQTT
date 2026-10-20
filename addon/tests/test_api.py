"""Tests for the FastAPI layer (skipped when FastAPI is not installed)."""

import asyncio
import re
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi import HTTPException

from app import main, store


@pytest.fixture(autouse=True)
def reset_state():
    main.STATE.config = store._normalize(None)
    main.STATE.client = None
    main.STATE.bridge = None
    main.STATE.ewelink_connected = False
    main.STATE.mqtt_connected = False
    main.STATE.ewelink_error = None
    yield


def make_body():
    return main.ConfigBody(
        ewelink=main.EWeLinkBody(username="me@example.com", password="pw"),
        mqtt=main.MQTTBody(host="broker.local", port=1883),
    )


def test_config_is_masked():
    view = asyncio.run(main.get_config())

    assert view["ewelink"]["password"] == ""
    assert view["ewelink"]["has_password"] is False
    assert view["mqtt"]["password"] == ""


def test_status_without_client():
    status = asyncio.run(main.get_status())

    assert status["ewelink"]["connected"] is False
    assert status["devices"] == []
    assert status["version"] == main.APP_VERSION
    assert status["mqtt"]["discovery"] is True
    assert status["mqtt"]["prefix"] == "sonoff"


def test_app_version_matches_the_addon_manifest():
    manifest = Path(main.__file__).resolve().parents[1] / "config.yaml"
    match = re.search(
        r'^version:\s*"?([^"\s]+)"?', manifest.read_text(encoding="utf-8"), re.M
    )

    assert match, "addon/config.yaml has no version"
    assert match.group(1) == main.APP_VERSION


def test_logs_endpoint_returns_the_buffer():
    main.STATE.logs.clear()
    main.STATE.logs.append("one")
    main.STATE.logs.append("two")

    assert asyncio.run(main.get_logs()) == {"lines": ["one", "two"]}


def test_messages_endpoint_is_empty_without_bridge():
    assert asyncio.run(main.get_messages()) == {"messages": []}


def test_messages_endpoint_forwards_bridge_messages():
    class FakeBridge:
        def recent_messages(self):
            return [{"time": "10:00:00", "topic": "sonoff/bridge/status"}]

    main.STATE.bridge = FakeBridge()

    assert asyncio.run(main.get_messages())["messages"][0]["topic"] == (
        "sonoff/bridge/status"
    )


def test_device_state_returns_409_without_client():
    with pytest.raises(HTTPException) as error:
        asyncio.run(
            main.post_device_state("nope", main.StateBody(params={"switch": "on"}))
        )

    assert error.value.status_code == 409


class FakeClient:
    def __init__(self):
        self.devices = {"dev1": {"deviceid": "dev1"}}
        self.sent = []

    async def async_send(self, deviceid, params):
        self.sent.append((deviceid, params))


def test_unknown_device_returns_404():
    main.STATE.client = FakeClient()

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            main.post_device_state("nope", main.StateBody(params={"switch": "on"}))
        )

    assert error.value.status_code == 404


def test_device_state_is_forwarded():
    main.STATE.client = FakeClient()

    result = asyncio.run(
        main.post_device_state("dev1", main.StateBody(params={"switch": "on"}))
    )

    assert result == {"ok": True}
    assert main.STATE.client.sent == [("dev1", {"switch": "on"})]


def test_post_config_tests_mqtt_and_saves(monkeypatch):
    calls = []

    def fake_test_connection(*args):
        calls.append(args)

    async def fake_start_services(config):
        main.STATE.config = config

    monkeypatch.setattr(main, "test_connection", fake_test_connection)
    monkeypatch.setattr(main, "start_services", fake_start_services)
    monkeypatch.setattr(main, "save_config", lambda config: calls.append(config))

    result = asyncio.run(main.post_config(make_body()))

    assert result == {"ok": True}
    assert calls[0] == ("broker.local", 1883, None, None, False)
    assert calls[1]["ewelink"]["username"] == "me@example.com"


def test_post_config_rejects_unreachable_broker(monkeypatch):
    def fail(*args):
        raise OSError("connection refused")

    monkeypatch.setattr(main, "test_connection", fail)

    with pytest.raises(HTTPException) as error:
        asyncio.run(main.post_config(make_body()))

    assert error.value.status_code == 400
    assert "MQTT" in error.value.detail


def test_post_config_requires_credentials():
    body = main.ConfigBody(
        ewelink=main.EWeLinkBody(username="", password=""),
        mqtt=main.MQTTBody(host="broker.local"),
    )

    with pytest.raises(HTTPException) as error:
        asyncio.run(main.post_config(body))

    assert error.value.status_code == 400
    assert "eWeLink" in error.value.detail
