"""Platform for light integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

from .TagoNet import TagoFanHA


async def async_setup_entry(hass, entry: ConfigEntry, async_add_entities):
    tagodevice = hass.data[DOMAIN][entry.entry_id]
    new_items = list()

    for item in tagodevice.fans:
        new_items.append(TagoFanHA(proxy=item))

    if len(new_items):
        async_add_entities(new_items)
