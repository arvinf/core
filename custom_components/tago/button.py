"""Platform for light integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.components.button import (
    DOMAIN
)

_LOGGER = logging.getLogger(__name__)

from .TagoNet import TagoKeypadHA

async def async_setup_entry(hass, entry: ConfigEntry, async_add_entities):
    items : list[TagoKeypadHA.TagoButtonHA] = list()
    entities = entry.runtime_data
    for e in entities:
        if e.type in TagoKeypadHA.types:
            print(e.get_buttons())
            items.extend(e.get_buttons())

    async_add_entities(items)