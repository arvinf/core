"""TAGO hosts integration."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional, cast

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_DEVICE_ID,
    ATTR_ID,
    ATTR_SUGGESTED_AREA,
    CONF_HOST,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
import homeassistant.helpers.config_validation as cv

from .const import CONF_HOST, CONF_NET_KEY, DOMAIN
from .TagoNet import TagoBridge, TagoDevice, TagoModbus

PLATFORMS: list[str] = [Platform.LIGHT]

_LOGGER = logging.getLogger(__name__)

async def async_setup(hass: HomeAssistant, base_config: ConfigType) -> bool:
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
# 'tago-e89f6d09a35881c18a3f.local

    # Save tagonet instance, to be used by platforms
    hostname = entry.data.get(CONF_HOST)
    netkey = entry.data.get(CONF_NET_KEY, '')
    device = TagoDevice(hostname, netkey)
    print('--- entry ', entry.entry_id)

    # connect to device
    try:
        await device.connect(10)
        _LOGGER.info("All devices enumerated.")

        hass.data[DOMAIN][entry.entry_id] = device

        def bridge_events(
            entity: TagoBridge, entity_id: str, message: dict[str, str]
        ) -> None:
            data = {
                ATTR_ID: entity_id,
                "action": message.get("type"),
                "keypad": "0x{:2x}".format(message.get("address")),
                "key": message.get("key"),
                "duration": "long"
                if message.get("duration") > 1
                else "short",
            }
            hass.bus.fire("tago_event", data)

        device_registry = dr.async_get(hass)

        # Set handler to catch messages from bridges, such as modbus keypads
        for bridge in device.bridges:
            bridge.set_message_handler(bridge_events)

        # register device
        device_registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            configuration_url=f"http://{device.host}/",
            identifiers={(DOMAIN, device.uid)},
            serial_number=device.uid,
            manufacturer=device.manufacturer,
            name=device.name,
            model=device.model_desc,
            sw_version=device.fw_rev,
            hw_version=device.model_name,
        )

        await hass.config_entries.async_forward_entry_setups(
            entry, PLATFORMS
        )
    except TimeoutError:
        _LOGGER.error("Timedout waiting to connect to all TagoNet devices.")

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    print('unload')
    device = hass.data[DOMAIN][entry.entry_id]
    if device:
        await device.disconnect()
    print('close done')
    if unload_ok := await hass.config_entries.async_unload_platforms(
        entry, PLATFORMS
    ):
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
