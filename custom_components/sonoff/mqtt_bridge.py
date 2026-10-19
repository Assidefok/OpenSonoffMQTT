"""MQTT bridge for Sonoff devices (OpenSonoffMQTT fork).

Publishes device state to an MQTT broker and accepts commands from it.
The bridge ships its own MQTT client (paho-mqtt), so the Home Assistant MQTT
integration is optional: the wizard fills the broker details from it when it
is configured, otherwise the user can point to any broker.

Topics (``<prefix>`` is configurable, ``sonoff`` by default):

    <prefix>/<deviceid>/state         device snapshot, JSON (retained)
    <prefix>/<deviceid>/availability  online / offline (retained)
    <prefix>/<deviceid>/get           republish the current snapshot
    <prefix>/<deviceid>/set           send commands
    <prefix>/bridge/status            bridge online / offline (retained)
    <prefix>/bridge/devices           known devices list, JSON (retained)

``set`` accepts either a JSON object with eWeLink params
(``{"switch": "on"}``, ``{"brightness": 80}``, ``{"switches": [...]}``) or a
short form: ``ON`` / ``OFF`` / ``TOGGLE``.
"""

import asyncio
import json
import logging
from typing import Callable

from homeassistant.core import HomeAssistant

from .core.const import (
    CONF_MQTT_ENABLED,
    CONF_MQTT_HOST,
    CONF_MQTT_PASSWORD,
    CONF_MQTT_PORT,
    CONF_MQTT_PREFIX,
    CONF_MQTT_RETAIN,
    CONF_MQTT_TLS,
    CONF_MQTT_USERNAME,
    PRIVATE_KEYS,
)
from .core.ewelink import SIGNAL_DEVICE_ADDED, XDevice, XRegistry
from .core.mqtt_client import MQTTClient

_LOGGER = logging.getLogger(__name__)

DEFAULT_PREFIX = "sonoff"
DEFAULT_PORT = 1883

SHORT_COMMANDS = {
    "on": "on",
    "off": "off",
    "toggle": "toggle",
}


def _clean_prefix(prefix: str | None) -> str:
    prefix = (prefix or DEFAULT_PREFIX).strip().strip("/")
    if not prefix:
        return DEFAULT_PREFIX
    if "+" in prefix or "#" in prefix:
        _LOGGER.warning(
            "MQTT bridge: invalid prefix %r, using %s", prefix, DEFAULT_PREFIX
        )
        return DEFAULT_PREFIX
    return prefix


def _mqtt_integration_data(hass: HomeAssistant) -> dict:
    """Broker settings of the official MQTT integration, if configured."""
    entry = next(iter(hass.config_entries.async_entries("mqtt")), None)
    if entry is None:
        return {}
    return {**entry.data, **entry.options}


def suggested_defaults(hass: HomeAssistant) -> dict:
    """Pre-filled broker settings so the setup wizard is one click for most."""
    defaults = {
        "host": "localhost",
        "port": DEFAULT_PORT,
        "username": "",
        "password": "",
        "tls": False,
    }

    data = _mqtt_integration_data(hass)
    if data:
        certificate = str(data.get("certificate") or "").lower()
        defaults.update(
            host=data.get("broker") or defaults["host"],
            port=int(data.get("port") or DEFAULT_PORT),
            username=data.get("username") or "",
            password=data.get("password") or "",
            tls=certificate in ("auto", "custom"),
        )
        return defaults

    if "hassio" in getattr(hass.config, "components", ()):
        # Home Assistant OS with the Mosquitto add-on
        defaults["host"] = "core-mosquitto"

    return defaults


def _config_from_options(options: dict) -> dict | None:
    host = options.get(CONF_MQTT_HOST)
    if not host:
        return None
    return {
        "host": host,
        "port": int(options.get(CONF_MQTT_PORT) or DEFAULT_PORT),
        "username": options.get(CONF_MQTT_USERNAME) or None,
        "password": options.get(CONF_MQTT_PASSWORD) or None,
        "tls": bool(options.get(CONF_MQTT_TLS, False)),
        "prefix": options.get(CONF_MQTT_PREFIX) or DEFAULT_PREFIX,
        "retain": bool(options.get(CONF_MQTT_RETAIN, True)),
    }


def _config_from_hass(hass: HomeAssistant, options: dict) -> dict | None:
    data = _mqtt_integration_data(hass)
    if not data.get("broker"):
        return None
    certificate = str(data.get("certificate") or "").lower()
    return {
        "host": data["broker"],
        "port": int(data.get("port") or DEFAULT_PORT),
        "username": data.get("username") or None,
        "password": data.get("password") or None,
        "tls": certificate in ("auto", "custom"),
        "prefix": options.get(CONF_MQTT_PREFIX) or DEFAULT_PREFIX,
        "retain": bool(options.get(CONF_MQTT_RETAIN, True)),
    }


def resolve_config(hass: HomeAssistant, options: dict) -> dict | None:
    """Return the MQTT settings to use, or None when the bridge is disabled."""
    if not options.get(CONF_MQTT_ENABLED):
        return None
    return _config_from_options(options) or _config_from_hass(hass, options)


class MQTTBridge:
    """Publish Sonoff device state to MQTT and accept commands from MQTT."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        registry: XRegistry,
        config: dict,
    ) -> None:
        self.hass = hass
        self.registry = registry
        self.prefix = _clean_prefix(config.get("prefix"))
        self.retain = config.get("retain", True)

        self._client = MQTTClient(
            host=config["host"],
            port=config.get("port", DEFAULT_PORT),
            username=config.get("username"),
            password=config.get("password"),
            tls=config.get("tls", False),
            client_id=f"sonoff-{entry_id[:12]}",
            subscriptions=(f"{self.prefix}/+/set", f"{self.prefix}/+/get"),
            on_connect=self._client_connected,
            on_message=self._client_message,
        )

        self._unsubs: list[Callable[[], None]] = []
        self._device_unsubs: dict[str, Callable[[], None]] = {}

    # lifecycle

    async def async_start(self) -> None:
        self._unsubs.append(
            self.registry.dispatcher_connect(SIGNAL_DEVICE_ADDED, self._device_added)
        )
        for device in list(self.registry.devices.values()):
            self._track_device(device)

        self._client.start()

        _LOGGER.info(
            "MQTT bridge starting for %s:%s, prefix %s",
            self._client.host,
            self._client.port,
            self.prefix,
        )

    async def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()

        for unsub in self._device_unsubs.values():
            unsub()
        self._device_unsubs.clear()

        self._publish(f"{self.prefix}/bridge/status", "offline", retain=True)
        # give the network thread a moment to flush the last retained message
        await asyncio.sleep(0.2)
        self._client.stop()

    # paho callbacks: they run in the paho network thread

    def _client_connected(self) -> None:
        self._schedule(self._async_on_connected())

    def _client_message(self, topic: str, payload: bytes) -> None:
        self._schedule(self._async_handle_message(topic, payload))

    def _schedule(self, coro) -> None:
        try:
            asyncio.run_coroutine_threadsafe(coro, self.hass.loop)
        except RuntimeError:
            coro.close()

    async def _async_on_connected(self) -> None:
        _LOGGER.info(
            "MQTT bridge connected to %s:%s", self._client.host, self._client.port
        )
        self._publish(f"{self.prefix}/bridge/status", "online", retain=True)
        for did in list(self.registry.devices.keys()):
            await self._async_publish_state(did)
        await self._async_publish_device_list()

    # subscriptions

    def _track_device(self, device: XDevice) -> None:
        did = device["deviceid"]
        if did in self._device_unsubs:
            return

        def update(_params: dict | None = None) -> None:
            self.hass.async_create_task(self._async_publish_state(did))

        self._device_unsubs[did] = self.registry.dispatcher_connect(did, update)

    def _device_added(self, device: XDevice) -> None:
        self._track_device(device)
        self.hass.async_create_task(self._async_publish_state(device["deviceid"]))
        self.hass.async_create_task(self._async_publish_device_list())

    # MQTT messages

    async def _async_handle_message(self, topic: str, payload: bytes) -> None:
        parsed = self._parse_topic(topic)
        if not parsed:
            return

        did, action = parsed
        if isinstance(payload, bytes):
            text = payload.decode("utf-8", "replace")
        else:
            text = payload

        if action == "get":
            await self._async_publish_state(did)
            return

        device = self.registry.devices.get(did)
        if device is None:
            # another config entry (eWeLink account) may own this device
            _LOGGER.debug("MQTT bridge: unknown device %s", did)
            return

        params = self._parse_payload(text)
        if params is None:
            _LOGGER.warning("MQTT bridge: invalid payload for %s: %r", did, text)
            return

        try:
            await self.registry.send(device, params)
        except Exception as e:  # noqa: BLE001 - never break the MQTT loop
            _LOGGER.warning(
                "MQTT bridge: can't send %s to %s", params, did, exc_info=e
            )

    # publishing

    def _publish(self, topic: str, payload: str, retain: bool | None = None) -> None:
        self._client.publish(
            topic, payload, retain=self.retain if retain is None else retain
        )

    async def _async_publish_state(self, did: str) -> None:
        device = self.registry.devices.get(did)
        if device is None:
            return

        self._publish(
            f"{self.prefix}/{did}/state",
            json.dumps(self._snapshot(device), default=str),
            retain=self.retain,
        )
        self._publish(
            f"{self.prefix}/{did}/availability",
            "online" if self._is_online(device) else "offline",
            retain=True,
        )

    async def _async_publish_device_list(self) -> None:
        devices = sorted(
            (
                {
                    "deviceid": d.get("deviceid"),
                    "name": d.get("name"),
                    "uiid": (d.get("extra") or {}).get("uiid"),
                }
                for d in self.registry.devices.values()
            ),
            key=lambda d: (d["name"] or "", d["deviceid"] or ""),
        )
        self._publish(
            f"{self.prefix}/bridge/devices",
            json.dumps(devices, default=str),
            retain=True,
        )

    # helpers

    def _parse_topic(self, topic: str) -> tuple[str, str] | None:
        prefix = self.prefix + "/"
        if not topic.startswith(prefix):
            return None

        parts = topic[len(prefix):].split("/")
        if len(parts) != 2 or not parts[0]:
            return None

        return parts[0], parts[1]

    @staticmethod
    def _parse_payload(payload: str) -> dict | None:
        payload = (payload or "").strip()
        if not payload:
            return None

        try:
            data = json.loads(payload)
        except ValueError:
            data = None

        if isinstance(data, dict) and data:
            return data

        if data is not None:
            # JSON scalar, e.g. "on" or 1
            payload = str(data).lower()

        key = payload.lower()
        if key in SHORT_COMMANDS:
            return {"switch": SHORT_COMMANDS[key]}

        return None

    @staticmethod
    def _is_online(device: XDevice) -> bool:
        return bool(device.get("online") or device.get("local"))

    @staticmethod
    def _snapshot(device: XDevice) -> dict:
        params = {
            k: v
            for k, v in (device.get("params") or {}).items()
            if k not in PRIVATE_KEYS
        }
        extra = device.get("extra") or {}
        return {
            "deviceid": device.get("deviceid"),
            "name": device.get("name"),
            "uiid": extra.get("uiid"),
            "online": bool(device.get("online")),
            "local": bool(device.get("local")),
            "params": params,
        }
