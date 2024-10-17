"""Config flow for Tago integration."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components import zeroconf

from .const import (
    CONF_CA,
    CONF_CTRLR_URI,
    CONF_HOST,
    CONF_NETID,
    CONF_NETNAME,
    CONF_PIN,
    DOMAIN,
)
from .TagoNet import TagoController

_LOGGER = logging.getLogger(__name__)


class TagoConfigFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 7

    def __init__(self):
        self.data = {}
        self.link_task: asyncio.Task | None = None
        self.errors = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self.controller_hostname = user_input[CONF_HOST].strip()
            self.port = 7000

            return await self.async_step_try_link()

        return self.async_show_form(
            step_id="user", data_schema=vol.Schema(
                {vol.Required(CONF_HOST): str}
            ), errors=self.errors
        )

    async def async_step_zeroconf(
        self, discovery_info: zeroconf.ZeroconfServiceInfo
    ) -> ConfigFlowResult:
        # self.discovery_info = discovery_info
        if discovery_info:
            self.controller_hostname = discovery_info.hostname.removesuffix(
                '.').strip()
            self.port = discovery_info.port
            self.network_name = discovery_info.properties.get(
                'network_name', '')
            self.network_id = discovery_info.properties.get('network_id', '')
            await self.async_set_unique_id(self.network_id)
            self._abort_if_unique_id_configured({CONF_NETID: self.network_id})
            self.context.update(
                {
                    "title_placeholders": {
                        "network_name":  self.network_name
                    }
                }
            )

        return await self.async_step_zeroconf_confirm()

    async def async_step_zeroconf_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm zeroconf configuration."""
        if user_input is not None:
            if self.link_task:
                self.link_task.cancel()
            self.link_task = None
            return await self.async_step_try_link()

        self._set_confirm_only()
        return self.async_show_form(
            step_id="zeroconf_confirm",
            description_placeholders={
                CONF_NETNAME: self.network_name
            }
        )

    async def async_step_try_link(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Wait for user to approve link on TAGO Controller app"""
        self.errors = {}
        if self.link_task is None:
            self.link_task = self.hass.async_create_task(
                self.async_link_to_controller())

        if not self.link_task.done():
            return self.async_show_progress(
                step_id="try_link",
                progress_action="wait_for_link",
                progress_task=self.link_task
            )
        try:
            await self.link_task

        except Exception as err:
            _LOGGER.error(err)
            print(str(err))
            if str(err) == 'link failed':
                self.errors = {'base': 'link_failed'}
                return self.async_show_progress_done(next_step_id="link_fail")
            self.errors = {'base': 'cannot_connect'}
            return self.async_show_progress_done(next_step_id="user")
        finally:
            self.link_task = None

        return self.async_show_progress_done(next_step_id="link_success")

    async def async_step_link_fail(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Linking failed"""
        if user_input is not None:
            if self.link_task:
                self.link_task.cancel()
            self.link_task = None
            return await self.async_step_try_link()

        return self.async_show_form(
            step_id="link_fail",
            errors=self.errors
        )

    async def async_step_link_success(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        await self.async_set_unique_id(self.network_id)
        self._abort_if_unique_id_configured({CONF_NETID: self.network_id})

        """ Linking succeeded """
        logging.debug(f'successfully linked to tago controller for {
                      self.network_name} ({self.network_id})')
        return self.async_create_entry(
            title=self.network_name, data=self.data
        )

    async def async_link_to_controller(self) -> None:
        params: dict = await TagoController.link(self.controller_hostname, self.port)
        self.network_id = params.get('network_id')
        self.network_name = params.get('network_name')
        self.data[CONF_CTRLR_URI] = params.get('uri')
        self.data[CONF_PIN] = params.get('pin')
        self.data[CONF_CA] = params.get('ca')
        self.data[CONF_NETID] = params.get('network_id')
        self.data[CONF_NETNAME] = params.get(
            'network_name', 'Tago Lighting Network')
