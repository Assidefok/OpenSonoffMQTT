"""Home Assistant discovery published by the stand-alone app bridge."""

import json

from app import mqtt_bridge


class FakeClient:
    def __init__(self, **kwargs):
        self.published = []
        self.connected = True

    def publish(self, topic, payload, retain=False):
        self.published.append((topic, payload, retain))

    def start(self):
        self.connected = True

    def stop(self):
        self.connected = False


async def _noop(deviceid, params):
    return None


def make_bridge(devices, monkeypatch, **mqtt):
    monkeypatch.setattr(mqtt_bridge, "MQTTClient", FakeClient)
    config = {"host": "broker", "prefix": "sonoff", **mqtt}
    return mqtt_bridge.MQTTBridge(
        config=config,
        devices_provider=lambda: devices,
        send_command=_noop,
        loop=None,
    )


def published(bridge):
    return {
        (topic, payload, retain)
        for topic, payload, retain in bridge._client.published
    }


def test_publish_all_publishes_switch_and_sensor(monkeypatch):
    devices = {
        "dev1": {
            "deviceid": "dev1",
            "name": "Kitchen",
            "online": True,
            "params": {"switch": "on", "power": "12.5"},
            "extra": {"uiid": 1, "productModel": "Sonoff Basic"},
        }
    }
    bridge = make_bridge(devices, monkeypatch)
    bridge.publish_all()

    messages = published(bridge)

    switch_topic = "homeassistant/switch/opensonoffmqtt_dev1_switch/config"
    payloads = {
        topic: json.loads(payload)
        for topic, payload, retain in messages
        if topic.endswith("/config")
    }
    assert switch_topic in payloads
    switch = payloads[switch_topic]
    assert switch["unique_id"] == "opensonoffmqtt_dev1_switch"
    assert switch["state_topic"] == "sonoff/dev1/state"
    assert switch["state_value_template"] == "{{ value_json.params.switch }}"
    assert switch["command_topic"] == "sonoff/dev1/set"
    assert json.loads(switch["payload_on"]) == {"switch": "on"}
    assert json.loads(switch["payload_off"]) == {"switch": "off"}
    assert switch["device"]["identifiers"] == ["opensonoffmqtt_dev1"]
    assert switch["device"]["name"] == "Kitchen"
    assert switch["availability_topic"] == "sonoff/dev1/availability"

    sensor_topic = "homeassistant/sensor/opensonoffmqtt_dev1_power/config"
    assert sensor_topic in payloads
    sensor = payloads[sensor_topic]
    assert sensor["device_class"] == "power"
    assert sensor["unit_of_measurement"] == "W"
    assert sensor["value_template"] == "{{ value_json.params.power }}"

    assert any(
        topic == "sonoff/dev1/state" and retain is True
        for topic, payload, retain in messages
    )
    assert ("sonoff/dev1/availability", "online", True) in messages


def test_discovery_can_be_disabled(monkeypatch):
    devices = {
        "dev1": {
            "deviceid": "dev1",
            "name": "Kitchen",
            "params": {"switch": "on"},
        }
    }
    bridge = make_bridge(devices, monkeypatch, discovery=False)
    bridge.publish_all()

    assert not [
        topic
        for topic, payload, retain in published(bridge)
        if topic.startswith("homeassistant/")
    ]


def test_removed_device_clears_its_discovery(monkeypatch):
    devices = {
        "dev1": {
            "deviceid": "dev1",
            "name": "Kitchen",
            "params": {"switch": "on"},
        }
    }
    bridge = make_bridge(devices, monkeypatch)
    bridge.publish_all()

    devices.clear()
    devices["dev2"] = {
        "deviceid": "dev2",
        "name": "Garage",
        "params": {"switch": "off"},
    }
    bridge.publish_all()

    cleared = [
        (topic, payload, retain)
        for topic, payload, retain in bridge._client.published
        if topic == "homeassistant/switch/opensonoffmqtt_dev1_switch/config"
    ]
    assert cleared[-1][1] == ""
    assert cleared[-1][2] is True
    assert any(
        topic == "homeassistant/switch/opensonoffmqtt_dev2_switch/config"
        for topic, payload, retain in bridge._client.published
    )


def test_multi_channel_switch_uses_json_payloads(monkeypatch):
    devices = {
        "dev1": {
            "deviceid": "dev1",
            "name": "Garage",
            "params": {"switch_2": "off"},
        }
    }
    bridge = make_bridge(devices, monkeypatch)
    bridge.publish_all()

    config = json.loads(
        next(
            payload
            for topic, payload, retain in bridge._client.published
            if topic == "homeassistant/switch/opensonoffmqtt_dev1_switch_2/config"
        )
    )
    assert config["name"] == "Switch 2"
    assert json.loads(config["payload_on"]) == {"switch_2": "on"}
    assert json.loads(config["payload_off"]) == {"switch_2": "off"}


def test_stop_marks_devices_offline(monkeypatch):
    devices = {
        "dev1": {
            "deviceid": "dev1",
            "name": "Kitchen",
            "params": {"switch": "on"},
        }
    }
    bridge = make_bridge(devices, monkeypatch)
    bridge.stop()

    assert ("sonoff/dev1/availability", "offline", True) in published(bridge)
    assert ("sonoff/bridge/status", "offline", True) in published(bridge)
