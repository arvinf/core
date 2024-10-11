"""Platform for light integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

from .TagoNet import TagoLightHA


async def async_setup_entry(hass, entry: ConfigEntry, async_add_entities):
    tagodevice = hass.data[DOMAIN][entry.entry_id]
    new_lights = list()

    for light in tagodevice.lights:
        new_lights.append(TagoLightHA(proxy=light))

    if len(new_lights):
        async_add_entities(new_lights)
