"""Config flow for Tago integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components import zeroconf

from .const import CONF_HOST, CONF_NET_KEY, DOMAIN
from .TagoNet import TagoDevice, model_num_to_desc

_LOGGER = logging.getLogger(__name__)


class TagoConfigFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self):
        self.data = {}

    async def async_step_zeroconf(
        self, discovery_info: zeroconf.ZeroconfServiceInfo
    ) -> ConfigFlowResult:
        self.discovery_info = discovery_info
        self.device_hostname = discovery_info.hostname.removesuffix('.').strip()
        self.device_serialnum = discovery_info.properties.get('serialnum', '')
        print('xxxx - async_step_zeroconf', discovery_info)

        ## TODO -- change to serial number
        await self.async_set_unique_id(self.device_serialnum)
        print('unique', self.device_serialnum)
        self._abort_if_unique_id_configured({CONF_HOST: self.device_hostname})

        self.device_name = self.discovery_info.properties.get('name', 'Tago Device'),
        self.device_model = model_num_to_desc(self.discovery_info.properties.get('model', 'unknown model'))

        self.context.update(
            {
                "title_placeholders": {
                    "serial_number":  self.device_serialnum,
                    "name": self.device_name,
                    "model": self.device_model
                }
            }
        )
        return await self.async_step_zeroconf_confirm()

    async def async_step_zeroconf_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a flow initiated by zeroconf."""
        if user_input is not None:
            hostname = self.discovery_info.hostname.removesuffix('.').strip()
            netkey = user_input[CONF_NET_KEY].strip()

            return await self.async_connect_and_add_device(hostname, netkey)

        return self.async_show_form(
            step_id="zeroconf_confirm", data_schema=vol.Schema(
                {vol.Optional(CONF_NET_KEY, default=''): str}
            ),
            errors={},
            description_placeholders={
                "serial_number":  self.device_serialnum,
                    "name": self.device_name,
                    "model": self.device_model
            },
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors = {}

        if user_input is not None:
            hostname = user_input[CONF_HOST].strip()
            netkey = user_input[CONF_NET_KEY].strip()

            return await self.async_connect_and_add_device(hostname, netkey)

        return self.async_show_form(
            step_id="user", data_schema=vol.Schema(
                {vol.Required(CONF_HOST): str,
                 vol.Optional(CONF_NET_KEY, default=''): str}
            ), errors=errors
        )

    async def async_connect_and_add_device(self, hostname, netkey) -> ConfigFlowResult:
        device = TagoDevice(hostname, netkey)
        ## connect to device
        try:
            if await device.connect(15):
                print('connect OK')
        except TimeoutError:
            return self.async_abort(reason="cannot_connect")

        name = device.name
        serialnum = device.serial_number
        await self.async_set_unique_id(serialnum)
        self._abort_if_unique_id_configured()

        self.data[CONF_NET_KEY] = netkey
        self.data[CONF_HOST] = hostname

        device.disconnect()

        return self.async_create_entry(
            title=name, data=self.data
        )
