"""OpenSonoffMQTT stand-alone app: FastAPI backend + web UI.

Runs as a Home Assistant add-on (ingress, port 8099) or as a plain Docker
container. Everything is configured from the web page: eWeLink account and
MQTT broker - no YAML.
"""

import asyncio
import logging
import os
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .ewelink.client import EWeLinkClient
from .mqtt_bridge import MQTTBridge
from .mqtt_client import test_connection
from .store import load_config, masked, merge_secrets, save_config

BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"

_LOGGER = logging.getLogger(__name__)


# --------------------------------------------------------------- status state
class AppState:
    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self.config: dict = {}
        self.client: EWeLinkClient | None = None
        self.bridge: MQTTBridge | None = None
        self.ewelink_connected = False
        self.ewelink_error: str | None = None
        self.mqtt_connected = False
        self.logs: deque[str] = deque(maxlen=200)


STATE = AppState()


class _LogHandler(logging.Handler):
    """Keep the last log lines for the web UI."""

    def __init__(self, buffer: deque) -> None:
        super().__init__()
        self.buffer = buffer

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.buffer.append(self.format(record))
        except Exception:  # noqa: BLE001 - logging must never raise
            pass


def setup_logging() -> None:
    level = (os.environ.get("LOG_LEVEL") or "info").upper()
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    root = logging.getLogger()
    if not any(isinstance(h, _LogHandler) for h in root.handlers):
        handler = _LogHandler(STATE.logs)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        handler.setLevel(logging.INFO)
        root.addHandler(handler)


# ------------------------------------------------------------------ lifecycle
async def start_services(config: dict) -> None:
    """(Re)start the eWeLink client and the MQTT bridge from a valid config."""
    ewelink = config["ewelink"]
    mqtt = config["mqtt"]

    client = EWeLinkClient(
        username=ewelink["username"],
        password=ewelink["password"],
        country_code=ewelink.get("country_code") or "",
        on_update=_on_device_update,
        on_status=_on_ewelink_status,
    )
    # raises AuthError/Exception when the login fails -> the caller shows it
    await client.async_start()

    bridge = None
    if mqtt.get("host"):
        bridge = MQTTBridge(
            config=mqtt,
            devices_provider=lambda: client.devices,
            send_command=client.async_send,
            loop=asyncio.get_running_loop(),
            on_status=_on_mqtt_status,
        )
        bridge.start()

    old_bridge, old_client = STATE.bridge, STATE.client
    STATE.client, STATE.bridge = client, bridge
    STATE.config = config
    STATE.ewelink_error = None

    if old_bridge is not None:
        old_bridge.stop()
    if old_client is not None:
        await old_client.async_stop()


async def stop_services() -> None:
    bridge, client = STATE.bridge, STATE.client
    STATE.bridge = STATE.client = None
    STATE.ewelink_connected = STATE.mqtt_connected = False
    if bridge is not None:
        bridge.stop()
    if client is not None:
        await client.async_stop()


def _on_device_update(device: dict) -> None:
    bridge = STATE.bridge
    if bridge is not None:
        bridge.publish_state(device["deviceid"])


def _on_ewelink_status(connected: bool, message: str) -> None:
    STATE.ewelink_connected = connected
    level = logging.INFO if connected else logging.WARNING
    _LOGGER.log(level, "eWeLink: %s", message)


def _on_mqtt_status(connected: bool, message: str) -> None:
    STATE.mqtt_connected = connected
    _LOGGER.info("MQTT: %s", message)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    STATE.config = load_config()
    if STATE.config["ewelink"]["username"] and STATE.config["ewelink"]["password"]:
        try:
            await start_services(STATE.config)
        except Exception as e:  # noqa: BLE001 - app must still start for the UI
            STATE.ewelink_error = str(e) or repr(e)
            _LOGGER.warning("Can't start services: %s", STATE.ewelink_error)
    yield
    await stop_services()


app = FastAPI(title="OpenSonoffMQTT", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ------------------------------------------------------------------- REST API
class EWeLinkBody(BaseModel):
    username: str = ""
    password: str = ""
    country_code: str = ""


class MQTTBody(BaseModel):
    host: str = ""
    port: int = 1883
    username: str = ""
    password: str = ""
    tls: bool = False
    prefix: str = "sonoff"
    retain: bool = True


class ConfigBody(BaseModel):
    ewelink: EWeLinkBody
    mqtt: MQTTBody


class StateBody(BaseModel):
    params: dict


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/config")
async def get_config() -> dict:
    return masked(STATE.config)


@app.post("/api/config")
async def post_config(body: ConfigBody) -> dict:
    config = merge_secrets(body.model_dump(), STATE.config)

    if not config["ewelink"]["username"] or not config["ewelink"]["password"]:
        raise HTTPException(400, "eWeLink email and password are required")
    if not config["mqtt"]["host"]:
        raise HTTPException(400, "MQTT broker address is required")

    async with STATE.lock:
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(
                None,
                test_connection,
                config["mqtt"]["host"],
                int(config["mqtt"]["port"] or 1883),
                config["mqtt"]["username"] or None,
                config["mqtt"]["password"] or None,
                bool(config["mqtt"]["tls"]),
            )
        except Exception as e:  # noqa: BLE001 - shown to the user
            raise HTTPException(400, f"Can't reach the MQTT broker: {e}") from e

        try:
            await start_services(config)
        except Exception as e:  # noqa: BLE001 - shown to the user
            raise HTTPException(400, f"eWeLink login failed: {e}") from e

        try:
            save_config(config)
        except OSError as e:
            raise HTTPException(500, f"Can't save the configuration: {e}") from e

    _LOGGER.info("Configuration saved and services restarted")
    return {"ok": True}


@app.get("/api/status")
async def get_status() -> dict:
    client = STATE.client
    return {
        "ewelink": {
            "connected": STATE.ewelink_connected,
            "error": STATE.ewelink_error,
        },
        "mqtt": {"connected": STATE.mqtt_connected},
        "devices": client.snapshot() if client is not None else [],
    }


@app.post("/api/devices/{deviceid}/state")
async def post_device_state(deviceid: str, body: StateBody) -> dict:
    client = STATE.client
    if client is None:
        raise HTTPException(409, "eWeLink is not connected yet")
    if deviceid not in client.devices:
        raise HTTPException(404, "Unknown device")

    try:
        await client.async_send(deviceid, body.params)
    except Exception as e:  # noqa: BLE001 - shown to the user
        raise HTTPException(400, f"Can't send the command: {e}") from e

    return {"ok": True}


@app.get("/api/logs")
async def get_logs() -> dict:
    return {"lines": list(STATE.logs)}
