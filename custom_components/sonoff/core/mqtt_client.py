"""Small paho-mqtt wrapper used by the Sonoff MQTT bridge.

It has no Home Assistant imports on purpose: the same code is meant to be
reused by the standalone OpenSonoffMQTT add-on/app later.

Works with both paho-mqtt 1.6 (Home Assistant < 2024.10) and 2.x.
"""

import logging
from typing import Callable, Iterable

import paho.mqtt.client as mqtt

_LOGGER = logging.getLogger(__name__)

try:  # paho-mqtt >= 2.0
    from paho.mqtt.client import CallbackAPIVersion

    _HAS_API_V2 = True
except ImportError:  # pragma: no cover - paho-mqtt 1.6 fallback
    CallbackAPIVersion = None
    _HAS_API_V2 = False


def _new_client(client_id: str):
    if _HAS_API_V2:
        return mqtt.Client(CallbackAPIVersion.VERSION2, client_id=client_id)
    return mqtt.Client(client_id=client_id)


def _is_failure(reason_code) -> bool:
    if hasattr(reason_code, "is_failure"):
        return bool(reason_code.is_failure)
    return reason_code not in (0, None)


class MQTTClient:
    """Threaded MQTT connection: callbacks run in the paho network thread."""

    def __init__(
        self,
        host: str,
        port: int = 1883,
        username: str | None = None,
        password: str | None = None,
        tls: bool = False,
        client_id: str = "",
        subscriptions: Iterable[str] = (),
        on_connect: Callable[[], None] | None = None,
        on_message: Callable[[str, bytes], None] | None = None,
    ) -> None:
        self.host = host
        self.port = int(port or 1883)
        self.subscriptions = list(subscriptions)
        self.on_connect = on_connect
        self.on_message = on_message

        self._connected = False
        self._stopping = False
        self._client = _new_client(client_id)
        self._client.reconnect_delay_set(min_delay=1, max_delay=30)

        if username:
            self._client.username_pw_set(username, password or None)
        if tls:
            self._client.tls_set()

        self._client.on_connect = self._handle_connect
        self._client.on_disconnect = self._handle_disconnect
        self._client.on_message = self._handle_message

    @property
    def connected(self) -> bool:
        return self._connected

    def start(self) -> None:
        """Connect in the background; paho reconnects automatically."""
        self._client.connect_async(self.host, self.port, keepalive=60)
        self._client.loop_start()

    def stop(self) -> None:
        self._stopping = True
        try:
            self._client.disconnect()
        except Exception:  # noqa: BLE001 - already disconnected
            pass
        finally:
            self._client.loop_stop()
            self._connected = False

    def publish(self, topic: str, payload: str, retain: bool = False) -> None:
        self._client.publish(topic, payload, qos=0, retain=retain)

    def subscribe(self, topic: str) -> None:
        self._client.subscribe(topic, qos=0)

    # paho callbacks (they run in the network thread)

    def _handle_connect(self, client, userdata, flags, reason_code, properties=None):
        if _is_failure(reason_code):
            _LOGGER.warning(
                "MQTT connection to %s:%s refused: %s",
                self.host,
                self.port,
                reason_code,
            )
            self._connected = False
            return

        self._connected = True
        _LOGGER.debug("MQTT connected to %s:%s", self.host, self.port)

        for topic in self.subscriptions:
            client.subscribe(topic, qos=0)

        if self.on_connect:
            self.on_connect()

    def _handle_disconnect(self, client, userdata, *args):
        self._connected = False
        if self._stopping:
            _LOGGER.debug("MQTT disconnected from %s:%s (stop)", self.host, self.port)
            return
        _LOGGER.warning(
            "MQTT disconnected from %s:%s, retrying in the background",
            self.host,
            self.port,
        )

    def _handle_message(self, client, userdata, msg):
        if self.on_message:
            self.on_message(msg.topic, msg.payload)


def test_connection(
    host: str,
    port: int = 1883,
    username: str | None = None,
    password: str | None = None,
    tls: bool = False,
    timeout: int = 10,
) -> None:
    """Try a real connection. Raises on failure, returns None when OK.

    Blocking call: run it in an executor.
    """
    client = _new_client("sonoff-setup-check")
    if username:
        client.username_pw_set(username, password or None)
    if tls:
        client.tls_set()

    try:
        client.connect(host, int(port or 1883), keepalive=timeout)
    finally:
        try:
            client.disconnect()
        except Exception:  # noqa: BLE001 - best effort
            pass
