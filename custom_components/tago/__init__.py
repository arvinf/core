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

from .const import CONF_CA, CONF_CTRLR_URI, CONF_PIN, CONF_CA, CONF_NETNAME, CONF_NETID, CONF_NODES, DOMAIN
from .TagoNet import TagoController, TagoGateway

PLATFORMS: list[str] = [Platform.LIGHT]

_LOGGER = logging.getLogger(__name__)

# async def async_setup(hass: HomeAssistant, base_config: ConfigType) -> bool:
#     print('async_setups')
#     hass.data.setdefault(DOMAIN, {})
#     return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})
    entry_data = hass.data[DOMAIN].setdefault(entry.entry_id, {})
    pin = entry.data.get(CONF_PIN, '3227191')
    ca = entry.data.get(CONF_CA, '')
    
    # entity_registry = er.async_get(hass)
    # device_registry = dr.async_get(hass)
    # if entry.data.get('foXXX'):
    #     print('XXXXXXXXXXXXXXX have data - ' + entry.data['foXXX'])
    # else:
    #     print('========== update')
    # hass.config_entries.async_update_entry(entry,  data={**entry.data, "foXXX": '888'})
        
    # print(entry.data)
    nodes = entry.data.get(CONF_NODES, [])

    ## TODO -- use zerconf to find 
    try:
        controller = TagoController(entry.data[CONF_CTRLR_URI], 
                                entry.data[CONF_CA],
                                pin)
        
        await controller.connect()
        nodes = await controller.list_nodes()
        if len(nodes):
            hass.config_entries.async_update_entry(entry,  data={**entry.data, CONF_NODES: nodes})
    except asyncio.TimeoutError:
        logging.warning(f'Could not connect to Tago controller for {entry.data[CONF_NETNAME]}')
        
    print(nodes)
    ## build device list
    # try:
    #     for n in nodes:
    #         gw = TagoGateway(uri=n['uri'], ca=ca, pin=pin)
    #         devices = await gw.list_devices()
    #         print(devices)
    # except asyncio.TimeoutError:
    #     logging.warning(f'Could not connect to Tago controller for {entry.data[CONF_NETNAME]}')

    # device_registry = dr.async_get(hass)
    # device_registry.async_get_or_create(
    #         config_entry_id=entry.entry_id,
    #         identifiers={(DOMAIN, device.uid)},
    #         serial_number=device.uid,
    #         manufacturer=device.manufacturer,
    #         name=device.name,
    #         model=device.model_desc,
    #         sw_version=device.fw_rev,
    #         hw_version=device.model_name,
    #     )

    # Save tagonet instance, to be used by platforms
    # hostname = entry.data.get(CONF_HOST)
    # netId = entry.data.get(CONF_NETID, '')
    # device = TagoDevice(hostname, netId)
    # print('--- entry ', entry.entry_id)

    # # connect to device
    # try:
    #     await device.connect(10)
    #     _LOGGER.info("All devices enumerated.")

    #     hass.data[DOMAIN][entry.entry_id] = device

    #     def bridge_events(
    #         entity: TagoBridge, entity_id: str, message: dict[str, str]
    #     ) -> None:
    #         data = {
    #             ATTR_ID: entity_id,
    #             "action": message.get("type"),
    #             "keypad": "0x{:2x}".format(message.get("address")),
    #             "key": message.get("key"),
    #             "duration": "long"
    #             if message.get("duration") > 1
    #             else "short",
    #         }
    #         hass.bus.fire("tago_event", data)

    #     device_registry = dr.async_get(hass)

    #     # Set handler to catch messages from bridges, such as modbus keypads
    #     for bridge in device.bridges:
    #         bridge.set_message_handler(bridge_events)

    #     # register device
    #     device_registry.async_get_or_create(
    #         config_entry_id=entry.entry_id,
    #         configuration_url=f"http://{device.host}/",
    #         identifiers={(DOMAIN, device.uid)},
    #         serial_number=device.uid,
    #         manufacturer=device.manufacturer,
    #         name=device.name,
    #         model=device.model_desc,
    #         sw_version=device.fw_rev,
    #         hw_version=device.model_name,
    #     )

    #     await hass.config_entries.async_forward_entry_setups(
    #         entry, PLATFORMS
    #     )
    # except TimeoutError:
    #     _LOGGER.error("Timedout waiting to connect to all TagoNet devices.")

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    print('unload')
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
        _LOGGER.debug("Unloaded entry for %s", entry.entry_id)

    return unload_ok

    # device = hass.data[DOMAIN][entry.entry_id]
    # if device:
    #     await device.disconnect()
    if unload_ok := await hass.config_entries.async_unload_platforms(
        entry, PLATFORMS
    ):
        pass
        # hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
