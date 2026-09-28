"""Config flow for MagentaCLOUD."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    MagentaCloudAuthenticationError,
    MagentaCloudClient,
    MagentaCloudError,
    MagentaCloudQuotaUnavailableError,
    MagentaCloudUrlError,
    MagentaCloudPermissionError,
    MagentaCloudTemporaryError,
)
from .const import CONF_URL, DEFAULT_URL, DOMAIN, CONF_BACKUP_ENABLED


async def _validate_input(hass: HomeAssistant, data: dict[str, Any]) -> None:
    """Validate credentials and quota support."""
    client = MagentaCloudClient(
        async_get_clientsession(hass),
        data[CONF_URL],
        data[CONF_USERNAME],
        data[CONF_PASSWORD],
    )
    await client.async_get_quota()


class MagentaCloudConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for MagentaCLOUD."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Offer backup storage separately from read-only monitoring."""
        return MagentaCloudOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input[CONF_URL] = user_input[CONF_URL].strip().rstrip("/")
            user_input[CONF_USERNAME] = user_input[CONF_USERNAME].strip()
            await self.async_set_unique_id(user_input[CONF_USERNAME].casefold())
            self._abort_if_unique_id_configured()
            try:
                await _validate_input(self.hass, user_input)
            except MagentaCloudAuthenticationError:
                errors["base"] = "invalid_auth"
            except MagentaCloudQuotaUnavailableError:
                errors["base"] = "quota_unavailable"
            except MagentaCloudUrlError:
                errors["base"] = "invalid_url"
            except MagentaCloudPermissionError:
                errors["base"] = "forbidden"
            except MagentaCloudTemporaryError:
                errors["base"] = "temporarily_unavailable"
            except MagentaCloudError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title=user_input[CONF_USERNAME],
                    data={key: value for key, value in user_input.items() if key != CONF_BACKUP_ENABLED},
                    options={CONF_BACKUP_ENABLED: user_input.get(CONF_BACKUP_ENABLED, False)},
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_URL, default=DEFAULT_URL): str,
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Optional(CONF_BACKUP_ENABLED, default=False): bool,
            }
        )
        return self.async_show_form(
            step_id="user", data_schema=schema, errors=errors
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> FlowResult:
        """Start reauthentication for an expired WebDAV session."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Validate and store a replacement session password."""
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {**self._reauth_entry.data, **user_input}
            try:
                await _validate_input(self.hass, data)
            except MagentaCloudAuthenticationError:
                errors["base"] = "invalid_auth"
            except MagentaCloudQuotaUnavailableError:
                errors["base"] = "quota_unavailable"
            except MagentaCloudUrlError:
                errors["base"] = "invalid_url"
            except MagentaCloudPermissionError:
                errors["base"] = "forbidden"
            except MagentaCloudTemporaryError:
                errors["base"] = "temporarily_unavailable"
            except MagentaCloudError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(
                    self._reauth_entry, data_updates=data
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            errors=errors,
        )


class MagentaCloudOptionsFlow(config_entries.OptionsFlow):
    """Explicitly opt into backup storage."""

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data={**self.config_entry.options, **user_input})
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required(
                    CONF_BACKUP_ENABLED,
                    default=self.config_entry.options.get(CONF_BACKUP_ENABLED, False),
                ): bool,
            }),
        )
