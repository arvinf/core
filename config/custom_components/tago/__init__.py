"""TAGO hosts integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    Platform,
)
from homeassistant.core import HomeAssistant

from .const import (
    CONF_HOSTSTR,
    CONF_AUTHKEY,
    DOMAIN,
)

from homeassistant.helpers.entity import DeviceInfo

from .TagoNet import TagoDevice

PLATFORMS: list[str] = [Platform.LIGHT, Platform.FAN,
                        Platform.SWITCH, Platform.COVER, Platform.BUTTON, Platform.SENSOR]

_LOGGER = logging.getLogger(__name__)


def generate_device_info(device: TagoDevice) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, device.unique_id)},
        name=device.name,
        manufacturer=device.manufacturer,
        model=device.model_num,
        configuration_url=device.dashboard_uri,
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})
    hoststr = entry.data.get(CONF_HOSTSTR) or ''
    authkey = entry.data.get(CONF_AUTHKEY) or ''

    entry_data = hass.data[DOMAIN].setdefault(entry.entry_id, {})

    logging.warning(' XXXXXX ' + hoststr + ' - ' + authkey)

    device = TagoDevice(hoststr, authkey)
    await device.connect()

    entry.runtime_data = device

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
