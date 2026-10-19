"""Home-Assistant-free eWeLink client for the standalone add-on.

``base.py``, ``cloud.py`` and ``local.py`` in this package are verbatim copies
of ``custom_components/sonoff/core/ewelink`` (they depend only on ``aiohttp``,
``cryptography`` and ``zeroconf``).  This module is a thin wrapper around
``XRegistryCloud`` and ``XRegistryLocal`` with the small API the add-on web UI
and MQTT bridge need: start/stop, the device dict, a serialisable snapshot,
commands and two callbacks.

Commands prefer the local network when the device was discovered over mDNS and
fall back to the cloud websocket otherwise.

Kept deliberately thin so the vendored modules above stay easy to re-sync.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from typing import Callable, Optional

from aiohttp import ClientSession
from zeroconf import Zeroconf

from .base import SIGNAL_CONNECTED, SIGNAL_UPDATE
from .cloud import REGIONS, XRegistryCloud
from .cloud import AuthError as AuthError  # re-exported for callers
from .local import XRegistryLocal

_LOGGER = logging.getLogger(__name__)

#: How long ``async_start`` waits for the first websocket connect attempt.
FIRST_CONNECT_TIMEOUT = 30.0


class EWeLinkClient:
    """Async eWeLink cloud client, usable without Home Assistant."""

    def __init__(
        self,
        username: str,
        password: str,
        country_code: str = "",
        on_update: Optional[Callable[[dict], None]] = None,
        on_status: Optional[Callable[[bool, str], None]] = None,
    ) -> None:
        self.username = username
        self.password = password
        self.country_code = country_code or ""
        self.on_update = on_update
        self.on_status = on_status

        self._session: ClientSession | None = None
        self._cloud: XRegistryCloud | None = None
        self._local: XRegistryLocal | None = None
        self._zeroconf: Zeroconf | None = None
        self._devices: dict[str, dict] = {}
        self._connected = False
        self._connected_event: asyncio.Event | None = None
        self._started = False

    # ------------------------------------------------------------------ API

    @property
    def devices(self) -> dict[str, dict]:
        """``deviceid`` -> device dict (same shape as ``get_devices`` items)."""
        return self._devices

    @property
    def connected(self) -> bool:
        """True while the cloud websocket is up."""
        return self._connected

    async def async_start(self) -> None:
        """Login, load devices and start the websocket loop.

        Raises ``AuthError`` on bad credentials so the web UI can show the
        problem.  Returns after the first connection attempt, successful or
        not; the background task keeps reconnecting afterwards.
        """
        if self._started:
            return

        country_code = self._login_country_code()

        self._connected_event = asyncio.Event()
        self._session = ClientSession(trust_env=False)
        self._cloud = XRegistryCloud(self._session)
        self._cloud.dispatcher_connect(SIGNAL_UPDATE, self._handle_update)
        self._cloud.dispatcher_connect(SIGNAL_CONNECTED, self._handle_connected)

        try:
            await self._cloud.login(
                username=self.username,
                password=self.password,
                country_code=country_code,
            )
            devices = await self._cloud.get_devices()
        except BaseException:
            await self._dispose()
            raise

        self._devices = {
            device["deviceid"]: device for device in devices if device.get("deviceid")
        }
        for device in self._devices.values():
            device.setdefault("params", {})

        _LOGGER.info(
            "eWeLink: logged in (region %s), %d device(s)",
            self._cloud.region,
            len(self._devices),
        )

        # LAN discovery is optional: without it everything goes through the cloud
        self._start_lan()

        self._started = True
        # keep the credentials so the ws loop can re-login when the token expires
        self._cloud.start(
            username=self.username,
            password=self.password,
            country_code=country_code,
        )

        try:
            await asyncio.wait_for(self._connected_event.wait(), FIRST_CONNECT_TIMEOUT)
        except asyncio.TimeoutError:
            _LOGGER.warning(
                "eWeLink: no websocket connect within %.0fs, retrying in background",
                FIRST_CONNECT_TIMEOUT,
            )

    def _start_lan(self) -> None:
        """Start mDNS discovery and LAN control (best effort)."""
        try:
            self._zeroconf = Zeroconf()
            self._local = XRegistryLocal(self._session)
            self._local.dispatcher_connect(SIGNAL_UPDATE, self._handle_local_update)
            self._local.start(self._zeroconf)
            _LOGGER.info("eWeLink: LAN discovery started")
        except Exception as e:  # noqa: BLE001 - LAN is optional
            _LOGGER.warning("eWeLink: LAN discovery not available: %s", e)
            self._local = None
            self._close_zeroconf()

    async def async_stop(self) -> None:
        """Cancel the websocket loop and close the HTTP session."""
        self._started = False

        cloud = self._cloud
        task = cloud.task if cloud is not None else None

        await self._dispose()

        if task is not None:
            with suppress(asyncio.CancelledError):
                await task

        self._devices.clear()
        self._connected = False

    async def async_send(self, deviceid: str, params: dict) -> None:
        """Send a command, preferring the local network when the device is found."""
        device = self._devices.get(deviceid)

        if device is None:
            _LOGGER.warning("eWeLink: can't send to unknown device %s", deviceid)
            return

        if self._local is not None and device.get("host"):
            result = await self._local.send(device, params, timeout=2)
            if result == "online":
                return
            _LOGGER.debug(
                "eWeLink: LAN send failed for %s (%s), using the cloud",
                deviceid,
                result,
            )

        cloud = self._cloud
        if cloud is None or not self._connected:
            _LOGGER.warning("eWeLink: can't send to %s, cloud disconnected", deviceid)
            return

        result = await cloud.send(device, params)
        if result not in (None, "online"):
            _LOGGER.debug("eWeLink: %s command result: %r", deviceid, result)

    def snapshot(self) -> list[dict]:
        """Small serialisable state of every device, sorted by name."""
        items = []
        for deviceid, device in self._devices.items():
            extra = device.get("extra") or {}
            items.append(
                {
                    "deviceid": deviceid,
                    "name": device.get("name") or deviceid,
                    "uiid": extra.get("uiid"),
                    "online": bool(device.get("online")),
                    "params": dict(device.get("params") or {}),
                }
            )
        items.sort(key=lambda item: item["name"].lower())
        return items

    # ------------------------------------------- callbacks from the registry

    def _handle_connected(self) -> None:
        connected = bool(self._cloud and self._cloud.online)
        self._connected = connected

        if self._connected_event is not None:
            self._connected_event.set()

        self._notify_status(
            connected,
            "websocket connected" if connected else "websocket disconnected",
        )

    def _handle_update(self, msg: dict) -> None:
        did = msg.get("deviceid")
        device = self._devices.get(did) if did else None
        if device is None:
            # the device may belong to another Home or account
            return

        params = msg.get("params")
        if not isinstance(params, dict):
            return

        device["cloud_seq"] = msg.get("sequence")

        # process online change
        if "online" in params:
            device["online"] = params["online"]
        elif device.get("online") is False and params.keys() != {"subDevRssi"}:
            # the cloud sends subDevRssi even for offline devices
            device["online"] = True

        state = {key: value for key, value in params.items() if key != "online"}
        if state:
            device.setdefault("params", {}).update(state)

        self._notify_update(device)

    def _handle_local_update(self, msg: dict) -> None:
        """Merge a message discovered on the LAN (same shape as the integration)."""
        did = msg.get("deviceid")
        if not did:
            return

        device = self._devices.get(did)
        params = msg.get("params")

        if not params:
            if device is None:
                return
            key = device.get("devicekey")
            if not key:
                return
            try:
                params = XRegistryLocal.decrypt_msg(msg, key)
            except Exception as e:  # noqa: BLE001 - wrong key or broken payload
                _LOGGER.debug("eWeLink: can't decrypt LAN message for %s: %s", did, e)
                return

        if not isinstance(params, dict):
            return

        if device is None:
            # DIY device visible on the LAN but not in the cloud account
            device = {
                "deviceid": did,
                "name": did,
                "extra": {"uiid": 0},
                "params": {},
                "local": True,
                "online": True,
            }
            self._devices[did] = device

        device.setdefault("params", {}).update(params)
        device["local"] = True
        device["online"] = True
        if host := msg.get("host"):
            device["host"] = host

        self._notify_update(device)

    def _notify_update(self, device: dict) -> None:
        if not self.on_update:
            return
        try:
            self.on_update(device)
        except Exception:  # noqa: BLE001 - a broken callback must not kill the ws loop
            _LOGGER.exception("eWeLink: on_update callback failed")

    def _notify_status(self, connected: bool, message: str) -> None:
        if not self.on_status:
            return
        try:
            self.on_status(connected, message)
        except Exception:  # noqa: BLE001 - a broken callback must not kill the ws loop
            _LOGGER.exception("eWeLink: on_status callback failed")

    def _login_country_code(self) -> str:
        country_code = (self.country_code or "").strip()
        if not country_code:
            # Same default as the Home Assistant integration: the API answers
            # error 10004 with the account region and login retries once.
            return "+86"
        if not country_code.startswith("+"):
            country_code = "+" + country_code
        if country_code not in REGIONS and self.username != "token":
            raise ValueError(f"Unknown country code: {country_code!r}")
        return country_code

    async def _dispose(self) -> None:
        """Tear down the websocket loop and the HTTP session (idempotent)."""
        cloud, self._cloud = self._cloud, None
        self._connected = False

        if cloud is not None:
            await cloud.stop()
            cloud.dispatcher.clear()

        local, self._local = self._local, None
        if local is not None:
            with suppress(Exception):
                await local.stop()
        self._close_zeroconf()

        session, self._session = self._session, None
        if session is not None and not session.closed:
            await session.close()

    def _close_zeroconf(self) -> None:
        zeroconf, self._zeroconf = self._zeroconf, None
        if zeroconf is not None:
            with suppress(Exception):
                zeroconf.close()
