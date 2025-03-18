"""Platform for light integration."""
from __future__ import annotations
from .TagoNet import TagoLight, TagoDevice
from .entity import TagoEntityHA

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.components.light import (
    DOMAIN,
    ATTR_BRIGHTNESS,
    ATTR_TRANSITION,
    ATTR_XY_COLOR,
    ATTR_WHITE,
    ATTR_COLOR_TEMP_KELVIN,
    ColorMode,
    LightEntity,
    LightEntityFeature
)

from .const import ATTR_RATE

_LOGGER = logging.getLogger(__name__)


class TagoLightHA(TagoEntityHA, LightEntity):
    _attr_supported_color_modes = [ColorMode.XY, ColorMode.COLOR_TEMP]
    _attr_supported_features  = LightEntityFeature.TRANSITION
    
    def __init__(self, entity: TagoLight):
        super().__init__(entity)
        self._entity: TagoLight = self._entity

    @property
    def is_dimmable(self):
        return self._entity.type != TagoLight.LIGHT_ONOFF

    @property
    def is_on(self):
        return self._entity.brightness > 0

    @property
    def supported_features(self) -> int | None:
        return LightEntityFeature.TRANSITION

    @property
    def supported_color_modes(self) -> set[ColorMode] | set[str] | None:
        if self._entity.type == TagoLight.LIGHT_MONO:
            return [ColorMode.BRIGHTNESS]
        elif self._entity.type == TagoLight.LIGHT_CCT:
            return [ColorMode.COLOR_TEMP]
        elif self._entity.type == TagoLight.LIGHT_RGB:
            return [ColorMode.XY]
        elif self._entity.type == TagoLight.LIGHT_RGBW:
            return [ColorMode.XY, ColorMode.WHITE]
        elif self._entity.type == TagoLight.LIGHT_RGB_CCT:
            return [ColorMode.XY, ColorMode.COLOR_TEMP]
        else:
            return [ColorMode.ONOFF]

    @property
    def brightness(self) -> int:
        return self.convert_value_from_device(self._entity.brightness)

    @property
    def color_mode(self):
        if self._entity.type == TagoLight.LIGHT_MONO:
            return ColorMode.BRIGHTNESS
        elif self._entity.type == TagoLight.LIGHT_RGB:
            return ColorMode.XY
        elif self._entity.type == TagoLight.LIGHT_RGBW:
            if self.xy_color[0] == 0 and self.xy_color[1] == 0:
                return ColorMode.WHITE
            else:
                return  ColorMode.XY
        elif self._entity.type == TagoLight.LIGHT_RGB_CCT:
            if self.xy_color[0] == 0 and self.xy_color[1] == 0:
                return ColorMode.COLOR_TEMP
            else:
                return  ColorMode.XY
        elif self._entity.type == TagoLight.LIGHT_CCT:
            return ColorMode.COLOR_TEMP
        else:
            return ColorMode.ONOFF

    @property
    def color_temp_kelvin(self) -> int | None:
        if self._entity.type in [TagoLight.LIGHT_RGB_CCT, TagoLight.LIGHT_CCT]:
            return int(self._entity.ct * (self._entity.colour_temp_range[1] - self._entity.colour_temp_range[0])) + self._entity.colour_temp_range[0]

        return None

    @property
    def min_color_temp_kelvin(self) -> int | None:
        if self._entity.type in [TagoLight.LIGHT_RGB_CCT, TagoLight.LIGHT_CCT]:
            return self._entity.colour_temp_range[0]

        return None

    @property
    def max_color_temp_kelvin(self) -> int | None:
        if self._entity.type in [TagoLight.LIGHT_RGB_CCT, TagoLight.LIGHT_CCT]:
            return self._entity.colour_temp_range[1]

        return None

    @property
    def xy_color(self) -> tuple[float, float] | None:
        if self._entity.type in [TagoLight.LIGHT_RGB, TagoLight.LIGHT_RGB_CCT, TagoLight.LIGHT_RGBW]:
            return (self._entity.colour_xy)
        return None

    async def async_turn_on(self, **kwargs):
        rate : float = kwargs.pop(ATTR_RATE, None)
        transition_time: float = kwargs.pop(ATTR_TRANSITION, None)
        brightness: float = kwargs.pop(ATTR_BRIGHTNESS, None)
        xy_color: tuple[float, float] | None = kwargs.pop(ATTR_XY_COLOR, None)
        white = kwargs.get(ATTR_WHITE, None)
        color_temp: int | None = kwargs.pop(ATTR_COLOR_TEMP_KELVIN, None)

        if white is not None:
            brightness = white

        if brightness is not None:
            brightness = self.convert_value_to_device(brightness)

        if color_temp is not None:
            # convert absolute colour temp to a ratio-metric value
            color_temp = (color_temp - self.min_color_temp_kelvin) / (self.max_color_temp_kelvin - self.min_color_temp_kelvin)
            await self._entity.set_ct(ct=color_temp, brightness=brightness, duration=transition_time, rate=rate)
            return

        if xy_color is not None:
            # colour doesn't have a "rate" only a duration
            await self._entity.set_colour(colour=xy_color, brightness=brightness, duration=transition_time)
            return

        if brightness is not None:
            await self._entity.set_brightness(brightness=brightness, duration=transition_time, rate=rate)
            return

    async def async_turn_off(self, **kwargs):
        rate : float = kwargs.pop(ATTR_RATE, None)
        transition_time: float = kwargs.pop(ATTR_TRANSITION, None)
        await self._entity.set_brightness(brightness=0, duration=transition_time, rate=rate)
        
    async def async_stop_transition(self):
        await self._entity.stop_ramp()

async def async_setup_entry(hass, entry: ConfigEntry, async_add_entities):
    lights: list[TagoLightHA] = list()
    device: TagoDevice = entry.runtime_data
    for e in device.entities:
        if TagoLight.is_of_type(type=e.type):
            lights.append(TagoLightHA(e))

    async_add_entities(lights)
