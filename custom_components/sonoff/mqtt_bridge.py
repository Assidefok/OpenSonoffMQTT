"""MQTT bridge for Sonoff devices.

OpenSonoffMQTT fork feature. It reuses the MQTT broker already configured in
Home Assistant (the official ``mqtt`` integration), so there is no second
broker configuration and no second connection to eWeLink.

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

import json
import logging
from typing import Callable

from homeassistant.core import HomeAssistant, callback

from .core.const import PRIVATE_KEYS
from .core.ewelink import SIGNAL_DEVICE_ADDED, XDevice, XRegistry

_LOGGER = logging.getLogger(__name__)

DEFAULT_PREFIX = "sonoff"

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


class MQTTBridge:
    """Publish Sonoff device state to MQTT and accept commands from MQTT."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        registry: XRegistry,
        prefix: str = DEFAULT_PREFIX,
        retain: bool = True,
    ) -> None:
        self.hass = hass
        self.entry_id = entry_id
        self.registry = registry
        self.prefix = _clean_prefix(prefix)
        self.retain = retain

        self._mqtt = None
        self._unsubs: list[Callable[[], None]] = []
        self._device_unsubs: dict[str, Callable[[], None]] = {}

    # lifecycle

    async def async_start(self) -> None:
        from homeassistant.components import mqtt

        self._mqtt = mqtt

        self._unsubs.append(
            await mqtt.async_subscribe(
                self.hass, f"{self.prefix}/+/set", self._handle_set
            )
        )
        self._unsubs.append(
            await mqtt.async_subscribe(
                self.hass, f"{self.prefix}/+/get", self._handle_get
            )
        )
        self._unsubs.append(
            self.registry.dispatcher_connect(SIGNAL_DEVICE_ADDED, self._device_added)
        )

        for device in list(self.registry.devices.values()):
            self._track_device(device)

        await self._publish(f"{self.prefix}/bridge/status", "online", retain=True)
        for did in list(self.registry.devices.keys()):
            await self._async_publish_state(did)
        await self._async_publish_device_list()

        _LOGGER.info(
            "MQTT bridge started on prefix %s with %d devices",
            self.prefix,
            len(self.registry.devices),
        )

    async def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()

        for unsub in self._device_unsubs.values():
            unsub()
        self._device_unsubs.clear()

        try:
            await self._publish(f"{self.prefix}/bridge/status", "offline", retain=True)
        except Exception:  # noqa: BLE001 - broker may be gone during shutdown
            pass

        self._mqtt = None

    # subscription helpers

    def _track_device(self, device: XDevice) -> None:
        did = device["deviceid"]
        if did in self._device_unsubs:
            return

        def update(_params: dict | None = None) -> None:
            self.hass.async_create_task(self._async_publish_state(did))

        self._device_unsubs[did] = self.registry.dispatcher_connect(did, update)

    @callback
    def _device_added(self, device: XDevice) -> None:
        self._track_device(device)
        self.hass.async_create_task(self._async_publish_state(device["deviceid"]))
        self.hass.async_create_task(self._async_publish_device_list())

    # MQTT callbacks

    @callback
    def _handle_set(self, msg) -> None:
        parsed = self._parse_topic(msg.topic)
        if not parsed or parsed[1] != "set":
            return

        did = parsed[0]
        device = self.registry.devices.get(did)
        if device is None:
            # another config entry (eWeLink account) may own this device
            _LOGGER.debug("MQTT bridge: unknown device %s", did)
            return

        params = self._parse_payload(msg.payload)
        if params is None:
            _LOGGER.warning(
                "MQTT bridge: invalid payload for %s: %r", did, msg.payload
            )
            return

        self.hass.async_create_task(self._async_send(device, params))

    @callback
    def _handle_get(self, msg) -> None:
        parsed = self._parse_topic(msg.topic)
        if not parsed or parsed[1] != "get":
            return
        self.hass.async_create_task(self._async_publish_state(parsed[0]))

    # actions

    async def _async_send(self, device: XDevice, params: dict) -> None:
        try:
            await self.registry.send(device, params)
        except Exception as e:  # noqa: BLE001 - never break the MQTT loop
            _LOGGER.warning(
                "MQTT bridge: can't send %s to %s",
                params,
                device["deviceid"],
                exc_info=e,
            )

    async def _async_publish_state(self, did: str) -> None:
        device = self.registry.devices.get(did)
        if device is None:
            return

        payload = json.dumps(self._snapshot(device), default=str)
        await self._publish(
            f"{self.prefix}/{did}/state", payload, retain=self.retain
        )
        await self._publish(
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
        await self._publish(
            f"{self.prefix}/bridge/devices",
            json.dumps(devices, default=str),
            retain=True,
        )

    async def _publish(
        self, topic: str, payload: str, retain: bool | None = None
    ) -> None:
        if self._mqtt is None:
            return
        await self._mqtt.async_publish(
            self.hass,
            topic,
            payload,
            qos=0,
            retain=self.retain if retain is None else retain,
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
