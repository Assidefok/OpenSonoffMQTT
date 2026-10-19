"""Tests for LAN/cloud command routing and state merging."""

import asyncio

from app.ewelink import client as client_module
from app.ewelink.client import EWeLinkClient


class FakeLocal:
    def __init__(self, result="online"):
        self.result = result
        self.sent = []

    async def send(self, device, params, timeout=5):
        self.sent.append((device["deviceid"], params))
        return self.result


class FakeCloud:
    def __init__(self):
        self.sent = []

    async def send(self, device, params=None):
        self.sent.append((device["deviceid"], params))
        return "online"


def make_client():
    updates = []
    client = EWeLinkClient("user", "pass", on_update=updates.append)
    client._devices = {
        "dev1": {"deviceid": "dev1", "host": "192.168.1.20", "params": {}}
    }
    client._cloud = FakeCloud()
    client._connected = True
    client._local = FakeLocal("online")
    return client, updates


def test_command_goes_over_lan_when_possible():
    client, _ = make_client()

    asyncio.run(client.async_send("dev1", {"switch": "on"}))

    assert client._local.sent == [("dev1", {"switch": "on"})]
    assert client._cloud.sent == []


def test_command_falls_back_to_cloud():
    client, _ = make_client()
    client._local = FakeLocal("timeout")

    asyncio.run(client.async_send("dev1", {"switch": "off"}))

    assert client._cloud.sent == [("dev1", {"switch": "off"})]


def test_cloud_only_device_skips_lan():
    client, _ = make_client()
    client._devices["dev2"] = {"deviceid": "dev2", "params": {}}

    asyncio.run(client.async_send("dev2", {"switch": "on"}))

    assert client._cloud.sent == [("dev2", {"switch": "on"})]
    assert client._local.sent == []


def test_local_update_merges_state():
    client, updates = make_client()

    client._handle_local_update(
        {"deviceid": "dev1", "params": {"switch": "on", "rssi": -50}}
    )

    device = client._devices["dev1"]
    assert device["params"]["switch"] == "on"
    assert device["params"]["rssi"] == -50
    assert device["local"] is True
    assert device["online"] is True
    assert updates


def test_lan_only_diy_device_is_registered():
    client, _ = make_client()

    client._handle_local_update({"deviceid": "diy1", "params": {"switch": "off"}})

    assert "diy1" in client._devices
    assert client._devices["diy1"]["name"] == "diy1"


def test_encrypted_message_without_key_is_ignored():
    client, _ = make_client()
    before = len(client._devices)

    client._handle_local_update({"deviceid": "enc1", "data": "abc", "iv": "def"})

    assert len(client._devices) == before


def test_encrypted_message_with_key_is_decrypted(monkeypatch):
    client, _ = make_client()
    client._devices["enc2"] = {"deviceid": "enc2", "devicekey": "key", "params": {}}

    monkeypatch.setattr(
        client_module.XRegistryLocal,
        "decrypt_msg",
        staticmethod(lambda msg, key: {"switch": "on"}),
    )
    client._handle_local_update({"deviceid": "enc2", "data": "abc", "iv": "def"})

    assert client._devices["enc2"]["params"]["switch"] == "on"
