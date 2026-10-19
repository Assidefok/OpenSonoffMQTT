"""MQTT bridge for the standalone OpenSonoffMQTT app.

Same topic contract as the Home Assistant integration:

    <prefix>/<deviceid>/state         JSON snapshot (retained)
    <prefix>/<deviceid>/availability  online / offline (retained)
    <prefix>/<deviceid>/get           republish the current snapshot
    <prefix>/<deviceid>/set           JSON params or ON / OFF / TOGGLE
    <prefix>/bridge/status            online / offline (retained)
    <prefix>/bridge/devices           device list, JSON (retained)

It is transport-only and has no Home Assistant imports: the app passes a
``devices_provider`` (dict deviceid -> device) and an async ``send_command``.
"""

import asyncio
import json
import logging
from typing import Awaitable, Callable

from .mqtt_client import MQTTClient

_LOGGER = logging.getLogger(__name__)

DEFAULT_PREFIX = "sonoff"
SHORT_COMMANDS = {"on": "on", "off": "off", "toggle": "toggle"}
PRIVATE_KEYS = ("bindInfos", "bssid", "mac", "p2pinfo", "ssid", "staMac", "timers")


def clean_prefix(prefix: str | None) -> str:
    prefix = (prefix or DEFAULT_PREFIX).strip().strip("/")
    if not prefix:
        return DEFAULT_PREFIX
    if "+" in prefix or "#" in prefix:
        return DEFAULT_PREFIX
    return prefix


class MQTTBridge:
    def __init__(
        self,
        config: dict,
        devices_provider: Callable[[], dict],
        send_command: Callable[[str, dict], Awaitable[None]],
        loop: asyncio.AbstractEventLoop,
        on_status: Callable[[bool, str], None] | None = None,
    ) -> None:
        self.prefix = clean_prefix(config.get("prefix"))
        self.retain = bool(config.get("retain", True))
        self._devices = devices_provider
        self._send = send_command
        self._loop = loop
        self._on_status = on_status

        self._client = MQTTClient(
            host=config["host"],
            port=int(config.get("port") or 1883),
            username=config.get("username") or None,
            password=config.get("password") or None,
            tls=bool(config.get("tls", False)),
            client_id="opensonoffmqtt-app",
            subscriptions=(f"{self.prefix}/+/set", f"{self.prefix}/+/get"),
            on_connect=self._connected,
            on_message=self._message,
        )

    @property
    def connected(self) -> bool:
        return self._client.connected

    def start(self) -> None:
        self._client.start()

    def stop(self) -> None:
        self._client.publish(f"{self.prefix}/bridge/status", "offline", retain=True)
        self._client.stop()

    # state publishing (called by the app when eWeLink sends an update)

    def publish_state(self, deviceid: str) -> None:
        device = self._devices().get(deviceid)
        if not device:
            return

        self._client.publish(
            f"{self.prefix}/{deviceid}/state",
            json.dumps(self._snapshot(device), default=str),
            retain=self.retain,
        )
        self._client.publish(
            f"{self.prefix}/{deviceid}/availability",
            "online" if self._is_online(device) else "offline",
            retain=True,
        )

    def publish_all(self) -> None:
        for deviceid in list(self._devices()):
            self.publish_state(deviceid)
        self.publish_device_list()

    def publish_device_list(self) -> None:
        devices = sorted(
            (
                {
                    "deviceid": d.get("deviceid"),
                    "name": d.get("name"),
                    "uiid": (d.get("extra") or {}).get("uiid"),
                }
                for d in self._devices().values()
            ),
            key=lambda d: (d["name"] or "", d["deviceid"] or ""),
        )
        self._client.publish(
            f"{self.prefix}/bridge/devices",
            json.dumps(devices, default=str),
            retain=True,
        )

    # paho callbacks

    def _connected(self) -> None:
        _LOGGER.info("MQTT connected, prefix %s", self.prefix)
        if self._on_status:
            self._on_status(True, "connected")
        self._client.publish(f"{self.prefix}/bridge/status", "online", retain=True)
        self._schedule(self._publish_all_async())

    async def _publish_all_async(self) -> None:
        self.publish_all()

    def _message(self, topic: str, payload: bytes) -> None:
        self._schedule(self._handle(topic, payload))

    async def _handle(self, topic: str, payload: bytes) -> None:
        prefix = self.prefix + "/"
        if not topic.startswith(prefix):
            return

        parts = topic[len(prefix):].split("/")
        if len(parts) != 2 or not parts[0]:
            return

        deviceid, action = parts
        text = payload
        if isinstance(payload, bytes):
            text = payload.decode("utf-8", "replace")

        if action == "get":
            self.publish_state(deviceid)
            return

        params = self._parse_payload(text)
        if params is None:
            _LOGGER.warning("Invalid MQTT payload for %s: %r", deviceid, text)
            return

        try:
            await self._send(deviceid, params)
        except Exception as e:  # noqa: BLE001 - never break the MQTT loop
            _LOGGER.warning("Can't send %s to %s", params, deviceid, exc_info=e)

    def _schedule(self, coro) -> None:
        try:
            asyncio.run_coroutine_threadsafe(coro, self._loop)
        except RuntimeError:
            coro.close()

    # helpers

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
            payload = str(data).lower()

        key = payload.lower()
        if key in SHORT_COMMANDS:
            return {"switch": SHORT_COMMANDS[key]}

        return None

    @staticmethod
    def _is_online(device: dict) -> bool:
        return bool(device.get("online") or device.get("local"))

    @staticmethod
    def _snapshot(device: dict) -> dict:
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
