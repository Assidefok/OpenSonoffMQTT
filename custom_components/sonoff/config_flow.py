from functools import lru_cache

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.config_entries import (
    SOURCE_IMPORT,
    ConfigEntry,
    ConfigFlow,
    OptionsFlow,
)
from homeassistant.const import CONF_MODE, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .core.const import (
    CONF_COUNTRY_CODE,
    CONF_DEBUG,
    CONF_MODES,
    CONF_MQTT_ENABLED,
    CONF_MQTT_HOST,
    CONF_MQTT_PASSWORD,
    CONF_MQTT_PORT,
    CONF_MQTT_PREFIX,
    CONF_MQTT_RETAIN,
    CONF_MQTT_TLS,
    CONF_MQTT_USERNAME,
    DOMAIN,
)
from .core.ewelink import XRegistryCloud
from .core.ewelink.cloud import REGIONS
from .mqtt_bridge import suggested_defaults


class FlowHandler(ConfigFlow, domain=DOMAIN):
    @property
    @lru_cache(maxsize=1)
    def cloud(self):
        session = async_get_clientsession(self.hass)
        return XRegistryCloud(session)

    async def async_step_import(self, user_input=None):
        return await self.async_step_user(user_input)

    async def async_step_user(self, user_input: dict = None):
        codes = {k: f"{v[0]} | {k}" for k, v in REGIONS.items()}

        data_schema = vol_schema(
            {
                vol.Required(CONF_USERNAME): str,
                vol.Optional(CONF_PASSWORD): str,
                vol.Optional(CONF_COUNTRY_CODE): vol.In(codes),
            },
            user_input,
        )

        if user_input is not None:
            username = user_input[CONF_USERNAME]
            password = user_input.get(CONF_PASSWORD)

            try:
                config_entry = await self.async_set_unique_id(username)
                if config_entry and password == "token":
                    # a special way to share a user's token
                    await self.cloud.login(**config_entry.data, app=1)
                    return self.async_show_form(
                        step_id="user",
                        data_schema=data_schema,
                        errors={"base": "template"},
                        description_placeholders={
                            "error": "Token: " + self.cloud.token,
                            "ewelink_url": "https://www.ewelink.cc/",
                        },
                    )

                if password:
                    await self.cloud.login(**user_input)

                if config_entry:
                    self.hass.config_entries.async_update_entry(
                        config_entry, data=user_input, unique_id=self.unique_id
                    )
                    # entry will reload automatically because
                    # `entry.update_listeners` linked to `async_update_options`
                    return self.async_abort(reason="reauth_successful")

                if self.source == SOURCE_IMPORT:
                    # YAML import has no UI: just create the entry, no MQTT
                    return self.async_create_entry(
                        title=username,
                        data={**user_input, CONF_MQTT_ENABLED: False},
                    )

                # guided setup: keep the credentials and ask for MQTT next
                self._ewelink_data = user_input
                return await self.async_step_mqtt()

            except Exception as e:
                return self.async_show_form(
                    step_id="user",
                    data_schema=data_schema,
                    errors={"base": "template"},
                    description_placeholders={
                        "error": repr(e),
                        "ewelink_url": "https://www.ewelink.cc/",
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            description_placeholders={"ewelink_url": "https://www.ewelink.cc/"},
        )

    async def async_step_mqtt(self, user_input: dict = None):
        """Guided MQTT setup: broker, credentials and test connection."""
        errors = {}

        if user_input is not None:
            error = await async_check_mqtt(self.hass, user_input)
            if not error:
                return self.async_create_entry(
                    title=self._ewelink_data[CONF_USERNAME],
                    data={**self._ewelink_data, **user_input},
                )
            errors["base"] = error

        data_schema = vol_schema(_mqtt_schema(self.hass, user_input), user_input)
        return self.async_show_form(
            step_id="mqtt",
            data_schema=data_schema,
            errors=errors,
            description_placeholders={
                "broker_hint": "Home Assistant OS with the Mosquitto add-on: "
                "host core-mosquitto, port 1883"
            },
        )

    async def async_step_reauth(self, user_input=None):
        return await self.async_step_user()

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry):
        return OptionsFlowHandler()


# noinspection PyUnusedLocal
class OptionsFlowHandler(OptionsFlow):
    @property
    def config_entry(self):
        return self.hass.config_entries.async_get_entry(self.handler)

    async def async_step_init(self, data: dict = None):
        errors = {}

        if data is not None:
            if data.get(CONF_MQTT_ENABLED):
                error = await async_check_mqtt(self.hass, data)
                if error:
                    errors["base"] = error
                else:
                    return self.async_create_entry(title="", data=data)
            else:
                return self.async_create_entry(title="", data=data)

        homes = {}

        if self.config_entry.data.get(CONF_PASSWORD):
            try:
                # important to use another accout for get user homes
                session = async_get_clientsession(self.hass)
                cloud = XRegistryCloud(session)
                await cloud.login(**self.config_entry.data, app=1)
                homes = await cloud.get_homes()
            except:  # noqa: E722
                pass

        for home in self.config_entry.options.get("homes", []):
            if home not in homes:
                homes[home] = home

        values = data if data is not None else dict(self.config_entry.options)
        schema = vol_schema(
            {
                vol.Optional(CONF_MODE, default="auto"): vol.In(CONF_MODES),
                vol.Optional(CONF_DEBUG, default=False): bool,
                vol.Optional("homes"): cv.multi_select(homes),
                **_mqtt_schema(self.hass, values),
            },
            {**self.config_entry.options, **values},
        )
        return self.async_show_form(
            step_id="init", data_schema=schema, errors=errors
        )


def _mqtt_schema(hass, values: dict | None = None) -> dict:
    suggested = suggested_defaults(hass)
    defaults = {
        CONF_MQTT_ENABLED: True,
        CONF_MQTT_HOST: suggested["host"],
        CONF_MQTT_PORT: suggested["port"],
        CONF_MQTT_USERNAME: suggested["username"],
        CONF_MQTT_PASSWORD: suggested["password"],
        CONF_MQTT_TLS: suggested["tls"],
        CONF_MQTT_PREFIX: "sonoff",
        CONF_MQTT_RETAIN: True,
    }
    defaults.update({k: v for k, v in (values or {}).items() if v is not None})

    return {
        vol.Optional(CONF_MQTT_ENABLED, default=defaults[CONF_MQTT_ENABLED]): bool,
        vol.Optional(CONF_MQTT_HOST, default=defaults[CONF_MQTT_HOST]): str,
        vol.Optional(CONF_MQTT_PORT, default=defaults[CONF_MQTT_PORT]): int,
        vol.Optional(CONF_MQTT_USERNAME, default=defaults[CONF_MQTT_USERNAME]): str,
        vol.Optional(CONF_MQTT_PASSWORD, default=defaults[CONF_MQTT_PASSWORD]): str,
        vol.Optional(CONF_MQTT_TLS, default=defaults[CONF_MQTT_TLS]): bool,
        vol.Optional(CONF_MQTT_PREFIX, default=defaults[CONF_MQTT_PREFIX]): str,
        vol.Optional(CONF_MQTT_RETAIN, default=defaults[CONF_MQTT_RETAIN]): bool,
    }


async def async_check_mqtt(hass, data: dict) -> str | None:
    """Return an error key when the broker is not reachable, None when OK."""
    if not data.get(CONF_MQTT_ENABLED):
        return None

    from .core.mqtt_client import test_connection

    try:
        await hass.async_add_executor_job(
            test_connection,
            data.get(CONF_MQTT_HOST),
            int(data.get(CONF_MQTT_PORT) or 1883),
            data.get(CONF_MQTT_USERNAME) or None,
            data.get(CONF_MQTT_PASSWORD) or None,
            bool(data.get(CONF_MQTT_TLS)),
        )
    except Exception as e:  # noqa: BLE001 - shown to the user as form error
        text = str(e).lower()
        if "authoriz" in text or "authoris" in text:
            return "invalid_auth"
        return "cannot_connect"

    return None


def vol_schema(schema: dict, defaults: dict | None) -> vol.Schema:
    if defaults:
        for key in schema:
            if (value := defaults.get(key.schema)) is not None:
                key.default = vol.default_factory(value)
    return vol.Schema(schema)
