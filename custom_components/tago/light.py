"""Platform for light integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.components.light import (
    DOMAIN
)

_LOGGER = logging.getLogger(__name__)

from .TagoNet import TagoLightHA

async def async_setup_entry(hass, entry: ConfigEntry, async_add_entities):
    lights : list[TagoLightHA] = list()
    entities = entry.runtime_data
    for e in entities:
        if e.is_of_domain(DOMAIN):
            lights.append(e)

    async_add_entities(lights)