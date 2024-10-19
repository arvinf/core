"""Platform for light integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.components.switch import (
    DOMAIN
)

_LOGGER = logging.getLogger(__name__)

from .TagoNet import TagoSwitchHA

async def async_setup_entry(hass, entry: ConfigEntry, async_add_entities):
    items : list[TagoSwitchHA] = list()
    entities = entry.runtime_data
    for e in entities:
        if e.is_of_domain(DOMAIN):
            items.append(e)

    async_add_entities(items)