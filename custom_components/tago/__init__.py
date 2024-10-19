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
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
import homeassistant.helpers.config_validation as cv

from .const import (
    CONF_CA,
    CONF_CTRLR_URI,
    CONF_NETID,
    CONF_NETNAME,
    CONF_NODES,
    CONF_PIN,
    DOMAIN,
)
from .TagoNet import TagoController, entities_from_nodes

PLATFORMS: list[str] = [Platform.LIGHT, Platform.FAN, Platform.SWITCH, Platform.COVER, Platform.BUTTON]

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})
    entry_data = hass.data[DOMAIN].setdefault(entry.entry_id, {})
    pin = entry.data.get(CONF_PIN, '3227191')
    ca = entry.data.get(CONF_CA, '')

    nodes = entry.data.get(CONF_NODES, [])

    # refresh node list from the controller
    try:
        controller = TagoController('wss://localhost:7000',
                                    entry.data[CONF_CA],
                                    pin)

        await controller.connect(timeout=4)
        nodes = await controller.list_nodes()
        if len(nodes):
            hass.config_entries.async_update_entry(
                entry,  data={**entry.data, CONF_NODES: nodes})
    except TimeoutError:
        logging.warning(f'Could not connect to Tago controller for {
                        entry.data[CONF_NETNAME]}')

    entities = entities_from_nodes(nodes)
    print(entities)
    entry.runtime_data = entities

    await hass.config_entries.async_forward_entry_setups(
        entry, PLATFORMS
    )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
        _LOGGER.debug("Unloaded entry for %s", entry.entry_id)

    return unload_ok
