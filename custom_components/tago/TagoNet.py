from __future__ import annotations
from typing import Callable, Dict, List, Optional, Tuple, Union, Coroutine, Any
import random
import string

import asyncio
from collections.abc import Callable
import json
import logging
import math

import ssl
from websockets.asyncio.client import connect as wsconnect

from homeassistant.components.fan import (
    DOMAIN as FAN_DOMAIN,
    FanEntity, FanEntityFeature,
)

from homeassistant.const import ATTR_SUGGESTED_AREA
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_TRANSITION,
    ATTR_HS_COLOR,
    ATTR_XY_COLOR,
    ATTR_WHITE,
    ATTR_COLOR_TEMP_KELVIN,
    ColorMode,
    LightEntity,
    LightEntityFeature,
    DOMAIN as LIGHT_DOMAIN
)
from homeassistant.util.percentage import (
    percentage_to_ranged_value,
    ranged_value_to_percentage,
)

from homeassistant.components.switch import (
    SwitchDeviceClass,
    SwitchEntity,
    SwitchEntityDescription,
    DOMAIN as SWITCH_DOMAIN
)

from homeassistant.components.cover import (
    DOMAIN as COVER_DOMAIN,
    ATTR_POSITION,
    CoverEntity, CoverEntityFeature, CoverDeviceClass
)

from homeassistant.components.button import ButtonEntity

from .const import (DOMAIN)

_LOGGER = logging.getLogger(__name__)


class TagoMessage:
    def __init__(self, message: str):
        # print('>> ' + str(message))
        data = json.loads(message)
        self.data = data
        self.rsp = data.get('rsp')
        self.src = data.get('src', '')
        self.ref = data.get('ref')
        self.evt = data.get('evt')

        if 'ref' in data:
            del data['ref']
        if 'src' in data:
            del data['src']
        if 'evt' in data:
            del data['evt']

    @property
    def content(self):
        return self.data

    @property
    def source(self):
        return self.src

    def refers_to(self, ref: str) -> bool:
        return (self.ref and self.ref == ref)

    def is_response(self, rsp: str = None) -> bool:
        if not rsp:
            return (self.rsp is not None)
        return (self.rsp and self.rsp == rsp)

    def is_event(self, evt: str = None) -> bool:
        if not evt:
            return (self.evt is not None)
        return (self.evt and self.evt == evt)

    @staticmethod
    def request(req: str, dst: str, data: dict = {}):
        data['req'] = req
        if dst:
            data['dst'] = dst
        return data


class TagoEntityHA:
    EVT_STATE_CHANGED = "state_changed"
    EVT_KEYPRESS = "key_pressed"
    EVT_KEYRELEASE = "key_released"

    MSG_GET_STATE = "get_state"

    RANGE_MAX = 65535

    def __init__(self, json: dict):
        self._uid = json['id']
        self._name = json.get('name', 'Unnamed')
        self._location = json.get('location', '')
        self._type = json.get('type', 'UNUSED')
        self._api = None

        if len(self._location.strip()):
            info = DeviceInfo(
                identifiers={
                    (
                        DOMAIN,
                        self._location
                    )
                },
                name=self._location,
                manufacturer='Tago',
                model="Virtual area device",
            )

            info[ATTR_SUGGESTED_AREA] = self._location
            self._attr_device_info = info

    def __repr__(self):
        return json.dumps({
            'id': self._uid,
            'name': self._name,
            'location': self._location,
            'type': self._type,
            'connected': self._api.is_connected() if self._api else False,
        }, indent=2)

    def set_api(self, api: TagoWebsocketClient):
        self._api: TagoWebsocketClient = api

    def is_of_domain(self, domain: str) -> bool:
        return False

    def update(self) -> None:
        self.schedule_update_ha_state()

    @property
    def type(self) -> str:
        return self._type

    @property
    def should_poll(self) -> bool:
        return False

    @property
    def has_entity_name(self) -> bool:
        return True

    @property
    def name(self) -> str:
        """Name"""
        return self._name

    @property
    def unique_id(self) -> str:
        """Unique id"""
        return self._uid

    @property
    def available(self) -> bool:
        """Available"""
        return self._api.is_connected()

    async def connection_state_changed(self, connected: bool) -> None:
        if connected:
            # request state refresh
            await self.send_request(req=self.MSG_GET_STATE)

        self.update()

    async def send_request(self, req: str, data: dict = {}) -> None:
        await self._api.send_request(TagoMessage.request(req=req, dst=self._uid, data=data))

    async def async_added_to_hass(self):
        print('async_added_to_hass')
        self._api.subscribe(TagoWebsocketClient.MESSAGE, self.handle_message)
        self._api.subscribe(TagoWebsocketClient.CONNECTION,
                            self.connection_state_changed)
        self.hass.async_create_task(self._api.connect())

    async def async_will_remove_from_hass(self):
        print('async_will_remove_from_hass')
        self._api.unsubscribe(TagoWebsocketClient.MESSAGE, self.handle_message)
        self._api.unsubscribe(TagoWebsocketClient.CONNECTION,
                              self.connection_state_changed)
        await self._api.disconnect(only_if_last=True, timeout=3)

    def handle_state_change(self, msg: TagoMessage) -> None:
        self.update()

    def handle_event(self, msg: TagoMessage) -> None:
        if msg.is_event(self.EVT_STATE_CHANGED):
            self.handle_state_change(msg)
        else:
            self.update()

    async def handle_message(self, msg: TagoMessage) -> None:
        if msg.source != self._uid:
            return

        if msg.is_event():
            self.handle_event(msg)
        elif msg.is_response(self.MSG_GET_STATE):
            self.handle_state_change(msg)

    @staticmethod
    def convert_value_to_device(
        intensity: float, srclimit: float = 255
    ) -> int:
        return int(round((intensity * TagoEntityHA.RANGE_MAX) / srclimit, 0))

    @staticmethod
    def convert_value_from_device(
        intensity: float, srclimit: float = 255
    ) -> float:
        return (intensity * srclimit) / TagoEntityHA.RANGE_MAX


class TagoBridge(TagoEntityHA):
    def __init__(self, json: dict):
        super().__init__(json)
        self._message_handler = None

    def set_message_handler(
        self, handler: Callable[[TagoBridge, str, dict]]
    ) -> None:
        self._message_handler = handler

    def forward_message(self, entity_id: str, message: dict) -> None:
        if self._message_handler is None:
            return

        self._message_handler(self, entity_id=entity_id, message=message)


class TagoLightHA(TagoEntityHA, LightEntity):
    LIGHT_ONOFF = "light"
    LIGHT_MONO = "light_dimmable"
    LIGHT_RGB = "light_rgb"
    LIGHT_RGBW = "light_rgbw"
    LIGHT_RGB_CCT = "light_rgbww"
    LIGHT_CCT = "light_ww"
    LIGHT_XY = "light_xycct"

    types = [LIGHT_ONOFF, LIGHT_MONO, LIGHT_RGB,
             LIGHT_RGBW, LIGHT_RGB_CCT, LIGHT_CCT]

    REQ_SET_LIGHT = "set_light"
    REQ_TURN_ON = "turn_on"
    REQ_TURN_OFF = "turn_off"

    STATE_ON = "on"
    STATE_OFF = "off"

    def __init__(self, json: dict):
        super().__init__(json)
        self._state = self.STATE_OFF
        self._brightness: int = 0
        self._colour_temp: int = 0
        self._colour_xy: tuple[float, float] = [0, 0]
        self._colour_hs: tuple[float, float] = [0, 0]
        self._colour_temp_range = [1400, 10000]

    def is_of_domain(self, domain: str) -> bool:
        return (domain == LIGHT_DOMAIN)

    @property
    def is_dimmable(self):
        return self._type != self.LIGHT_ONOFF

    @property
    def is_on(self):
        return self._state == self.STATE_ON and self._brightness > 0

    @property
    def supported_features(self) -> int | None:
        return LightEntityFeature.TRANSITION

    @property
    def supported_color_modes(self) -> set[ColorMode] | set[str] | None:
        if self._type == self.LIGHT_MONO:
            return [ColorMode.BRIGHTNESS]
        elif self._type == self.LIGHT_CCT:
            return [ColorMode.COLOR_TEMP]
        elif self._type == self.LIGHT_RGB:
            return [ColorMode.HS]
        elif self._type == self.LIGHT_RGBW:
            return [ColorMode.HS, ColorMode.WHITE]
        elif self._type == self.LIGHT_RGB_CCT:
            return [ColorMode.HS, ColorMode.COLOR_TEMP]
        elif self._type == self.LIGHT_XY:
            return [ColorMode.XY, ColorMode.COLOR_TEMP]
        else:
            return [ColorMode.ONOFF]

    @property
    def brightness(self) -> int:
        return self.convert_value_from_device(self._brightness)

    @property
    def color_mode(self):
        if self._type == self.LIGHT_MONO:
            return ColorMode.BRIGHTNESS
        elif self._type in [self.LIGHT_RGB, self.LIGHT_RGBW, self.LIGHT_RGB_CCT]:
            return ColorMode.HS
        elif self._type == self.LIGHT_CCT:
            return ColorMode.COLOR_TEMP
        elif self._type == self.LIGHT_XY:
            return ColorMode.XY
        else:
            return ColorMode.ONOFF

    @property
    def color_temp_kelvin(self) -> int | None:
        if self._type in [self.LIGHT_RGB_CCT, self.LIGHT_CCT]:
            relative = self.convert_value_from_device(self._colour_temp, 1.0)
            ct = int(
                relative * (self._colour_temp_range[1] - self._colour_temp_range[0])) + self._colour_temp_range[0]
            return ct

        return None

    @property
    def min_color_temp_kelvin(self) -> int | None:
        if self._type in [self.LIGHT_RGB_CCT, self.LIGHT_CCT]:
            return self._colour_temp_range[0]

        return None

    @property
    def max_color_temp_kelvin(self) -> int | None:
        if self._type in [self.LIGHT_RGB_CCT, self.LIGHT_CCT]:
            return self._colour_temp_range[1]

        return None

    @property
    def hs_color(self) -> tuple[float, float] | None:
        if self._type in [self.LIGHT_RGB, self.LIGHT_RGBW, self.LIGHT_RGB_CCT]:
            return (self.convert_value_from_device(self._colour_hs[0]),
                    self.convert_value_from_device(self._colour_hs[1]))

        return None

    @property
    def xy_color(self) -> tuple[float, float] | None:
        if self._type in [self.LIGHT_XY]:
            return (self.convert_value_from_device(self._colour_xy[0]),
                    self.convert_value_from_device(self._colour_xy[1]))
        return None

    async def async_turn_on(self, **kwargs):
        data = {}
        transition_time: float = kwargs.pop(ATTR_TRANSITION, 0.5)

        if transition_time is not None:
            data["rate"] = int((TagoEntityHA.RANGE_MAX * 6) /
                               (int(transition_time * 1000)))

        brightness: float = kwargs.pop(ATTR_BRIGHTNESS, None)
        xy_colour: tuple[float, float] | None = kwargs.pop(ATTR_XY_COLOR, None)
        hs_colour: tuple[float, float] | None = kwargs.pop(ATTR_HS_COLOR, None)
        white = kwargs.get(ATTR_WHITE, None)
        ct_colour: int | None = kwargs.pop(ATTR_COLOR_TEMP_KELVIN, None)

        if brightness:
            brightness = self.convert_value_to_device(brightness)
            min(max(brightness, 0), self.RANGE_MAX)
        elif white:  # TODO - when white is set, set rgb to 0
            brightness = self.convert_value_to_device(white)
            min(max(brightness, 0), self.RANGE_MAX)
        elif ct_colour:
            relative = (ct_colour - self._colour_temp_range[0]) / (
                self._colour_temp_range[1] - self._colour_temp_range[0])
            ct_colour = self.convert_value_to_device(
                max(min(relative, 1.0), 0), 1.0)

        if hs_colour:
            hs_colour = [self.convert_value_to_device(hs_colour[0]),
                         self.convert_value_to_device(hs_colour[1])]
        elif xy_colour:
            xy_colour = [self.convert_value_to_device(xy_colour[0]),
                         self.convert_value_to_device(xy_colour[1])]

        if brightness is None and \
                xy_colour is None and \
                hs_colour is None and \
                white is None and \
                ct_colour is None:
            await self.send_request(req=self.REQ_TURN_ON)
            return

        data = {}
        if brightness is not None:
            data['brightness'] = brightness

        if ct_colour is not None:
            data['ct'] = ct_colour

        if hs_colour is not None:
            data['hs'] = hs_colour

        await self.send_request(
            req=self.REQ_SET_LIGHT, data=data
        )

    async def async_turn_off(self, **kwargs):
        await self.send_request(req=self.REQ_TURN_OFF)

    def handle_state_change(self, msg: TagoMessage) -> None:
        data = msg.content
        self._state = data.get("state", self._state)
        self._brightness = data.get("brightness", self._brightness)
        self._colour_temp = data.get("ct", self._colour_temp)
        self._colour_temp_range = data.get(
            "ct_range", self._colour_temp_range)
        self._colour_xy = data.get("xy", self._colour_xy)
        self._colour_hs = data.get("hs", self._colour_hs)
        super().handle_state_change(msg=msg)


class TagoFanHA(TagoEntityHA, FanEntity):
    ONOFF = "fan"
    DIMMABLE = "fan_dimmable"

    types = [ONOFF, DIMMABLE]

    SPEED_RANGE = (0, TagoEntityHA.RANGE_MAX)

    REQ_SET_FAN = "set_fan"
    REQ_TURN_ON = "turn_on"
    REQ_TURN_OFF = "turn_off"

    STATE_ON = "on"
    STATE_OFF = "off"

    def __init__(self, json: dict):
        super().__init__(json)
        self._state = self.STATE_OFF
        self._value = [0]

    def is_of_domain(self, domain: str) -> bool:
        return (domain == FAN_DOMAIN)

    @property
    def is_on(self):
        return self._state == self.STATE_ON and self._value[0] > 0

    @property
    def supported_features(self) -> int | None:
        return FanEntityFeature.TURN_ON | FanEntityFeature.TURN_OFF if self._type == self.ONOFF else FanEntityFeature.TURN_ON | FanEntityFeature.TURN_OFF | FanEntityFeature.SET_SPEED

    @property
    def percentage(self) -> int | None:
        return ranged_value_to_percentage(self.SPEED_RANGE, self._value[0])

    async def async_turn_on(self, percentage, preset_mode, **kwargs):
        if (percentage):
            return self.async_set_percentage(percentage)

        await self.send_request(req=self.REQ_TURN_ON)

    async def async_turn_off(self, **kwargs):
        await self.send_request(req=self.REQ_TURN_OFF)

    async def async_set_percentage(self, percentage: int) -> None:
        if percentage == 0:
            await self.async_turn_off()
            return

        level = math.ceil(percentage_to_ranged_value(
            self.SPEED_RANGE, percentage))
        await self.send_request(
            REQ=self.MSG_SET_FAN, data={"value": [level]}
        )

    def handle_state_change(self, msg: TagoMessage) -> None:
        data = msg.content
        self._value = data.get("value", self._value)
        self._state = data.get("state", self._state)
        super().handle_state_change(msg=msg)


class TagoCoverHA(TagoEntityHA, CoverEntity):
    SHADE = "cover_shades"
    CURTAIN = "cover_curtains"
    GARGE_DOOR = "cover_garage_door"
    WINDOW = "cover_window"

    types = [SHADE, CURTAIN, GARGE_DOOR, WINDOW]

    REQ_STOP = "stop"
    REQ_MOVE_TO = "move_to"
    REQ_TURN_ON = "turn_on"
    REQ_TURN_OFF = "turn_off"

    STATE_ON = "on"
    STATE_OFF = "off"

    SPEED_RANGE = (0, TagoEntityHA.RANGE_MAX)

    def __init__(self, json: dict):
        super().__init__(json)
        self._position = 0
        self._target = 0
        if self._type == self.CURTAIN:
            self._attr_device_class = CoverDeviceClass.CURTAIN
        elif self._type == self.GARGE_DOOR:
            self._attr_device_class = CoverDeviceClass.GARAGE
        elif self._type == self.WINDOW:
            self._attr_device_class = CoverDeviceClass.WINDOW
        else:
            self._attr_device_class = CoverDeviceClass.SHADE

    def is_of_domain(self, domain: str) -> bool:
        return (domain == COVER_DOMAIN)

    @property
    def current_cover_position(self) -> int:
        return 100 - self._position

    @property
    def is_closed(self) -> bool:
        return self._position == 100

    @property
    def is_closing(self) -> bool:
        return self._target > self._position

    @property
    def is_opening(self) -> bool:
        return self._target < self._position

    @property
    def supported_features(self) -> int | None:
        return CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | CoverEntityFeature.STOP | CoverEntityFeature.SET_POSITION

    async def async_open_cover(self, **kwargs):
        """Open the cover."""
        await self.send_request(req=self.REQ_MOVE_TO, data={'target': 0})

    async def async_close_cover(self, **kwargs):
        """Close cover."""
        await self.send_request(req=self.REQ_MOVE_TO,  data={'target': 100})

    async def async_set_cover_position(self, **kwargs):
        """Move the cover to a specific position."""
        await self.send_request(req=self.REQ_MOVE_TO,  data={'target': 100-kwargs[ATTR_POSITION]})

    async def async_stop_cover(self, **kwargs):
        """Stop the cover."""
        await self.send_request(req=self.REQ_STOP)

    def handle_state_change(self, msg: TagoMessage) -> None:
        data = msg.content
        self._position = data.get("position", self._position)
        self._target = data.get("target", self._target)
        super().handle_state_change(msg=msg)


class TagoSwitchHA(TagoEntityHA, SwitchEntity):
    OUTLET = "relay_outlet"
    SWITCH = "relay_switch"

    types = [OUTLET, SWITCH]

    REQ_TURN_ON = "turn_on"
    REQ_TURN_OFF = "turn_off"

    STATE_ON = "on"
    STATE_OFF = "off"

    def __init__(self, json: dict):
        super().__init__(json)
        self._state = self.STATE_OFF

        if self._type == self.OUTLET:
            self._attr_device_class = SwitchDeviceClass.OUTLET
        else:
            self._attr_device_class = SwitchDeviceClass.SWITCH

    def is_of_domain(self, domain: str) -> bool:
        return (domain == SWITCH_DOMAIN)

    @property
    def is_on(self):
        return self._state == self.STATE_ON

    async def async_turn_on(self, **kwargs):
        await self.send_request(req=self.REQ_TURN_ON)

    async def async_turn_off(self, **kwargs):
        await self.send_request(req=self.REQ_TURN_OFF)

    def handle_state_change(self, msg: TagoMessage) -> None:
        data = msg.content
        self._state = data.get("state", self._state)
        super().handle_state_change(msg=msg)


class TagoKeypadHA(TagoEntityHA):
    KEYPAD_1 = "keypad:1"
    KEYPAD_2 = "keypad:2"
    KEYPAD_3 = "keypad:3"
    KEYPAD_4 = "keypad:4"
    KEYPAD_5 = "keypad:5"
    KEYPAD_6 = "keypad:6"
    KEYPAD_7 = "keypad:7"
    KEYPAD_8 = "keypad:8"
    KEYPAD_9 = "keypad:9"
    KEYPAD_10 = "keypad:10"
    KEYPAD_11 = "keypad:11"
    KEYPAD_12 = "keypad:12"
    KEYPAD_13 = "keypad:13"
    KEYPAD_14 = "keypad:14"
    KEYPAD_15 = "keypad:15"
    KEYPAD_16 = "keypad:16"

    types = [KEYPAD_1,
             KEYPAD_2,
             KEYPAD_3,
             KEYPAD_4,
             KEYPAD_5,
             KEYPAD_6,
             KEYPAD_7,
             KEYPAD_8,
             KEYPAD_9,
             KEYPAD_10,
             KEYPAD_11,
             KEYPAD_12,
             KEYPAD_13,
             KEYPAD_14,
             KEYPAD_15,
             KEYPAD_16,]

    class TagoButtonHA(ButtonEntity):
        def __init__(self, parent, key: int):
            self._index = key
            self._parent = parent
            self._name = f'Button {key+1}'
            
            location = self._parent._location
            
            if len(location.strip()):
                info = DeviceInfo(
                    identifiers={
                        (
                            DOMAIN,
                            self._parent.unique_id
                        )
                    },
                    name=f'{location} - {self._parent.name}',
                    manufacturer='Tago',
                    model=f"Keypad {key+1} Button",
                    # via_device={DOMAIN, location}
                )

                info[ATTR_SUGGESTED_AREA] = location
                self._attr_device_info = info
            else:
                info = DeviceInfo(
                    identifiers={
                        (
                            DOMAIN,
                            self._parent.unique_id
                        )
                    },
                    name=f'{self._parent.name}',
                    manufacturer='Tago',
                    model=f"Keypad {key+1} Button",
                )

                self._attr_device_info = info
                
            # if self._parent._attr_device_info:
            #     self._attr_device_info = self._parent._attr_device_info

        @property
        def should_poll(self) -> bool:
            return False

        @property
        def has_entity_name(self) -> bool:
            return True

        @property
        def name(self) -> str:
            """Name"""
            return self._name

        @property
        def unique_id(self) -> str:
            """Unique id"""
            return f'{self._parent.unique_id}:{self._index+1}'

        @property
        def available(self) -> bool:
            """Available"""
            return self._parent.available

        async def async_press(self) -> None:
            """Send a button press event."""
            await self._parent.press_button(self._index)

        async def async_added_to_hass(self):
            await self._parent.async_added_to_hass()

        async def async_will_remove_from_hass(self):
            await self._parent.async_will_remove_from_hass()

    def __init__(self, json: dict):
        super().__init__(json)
        self._key_count = int(self.type.split(':')[1])
        self._buttons: list[TagoKeypadHA.TagoButtonHA] = list()
        self._add_count = 0
        self._remove_count = 0
        for i in range(self._key_count):
            self._buttons.append(TagoKeypadHA.TagoButtonHA(self, i))

    def get_buttons(self) -> TagoButtonHA:
        return self._buttons

    async def press_button(self, key: int) -> None:
        print('press', key)

    async def async_added_to_hass(self) -> None:
        self.hass = self._buttons[0].hass
        if self._add_count == 0:
            await super().async_added_to_hass()
        self._add_count = self._add_count + 1

    async def async_will_remove_from_hass(self) -> None:
        if self._remove_count == self._key_count:
            await super().async_will_remove_from_hass()
        self._remove_count = self._remove_count + 1

    def update(self) -> None:
        for b in self._buttons:
            b.schedule_update_ha_state()

# class TagoKeypadHA(TagoBridge):
#     def handle_event(self, event: str, data: dict) -> None:
#         super().handle_event(event=event, data=data)
#         evt_map = {
#             self.EVT_KEYRELEASE: 'key_release',
#             self.EVT_KEYPRESS: 'keypress'
#         }

#         if event in evt_map:
#             self.forward_message(
#                 entity_id=data.get("id", ""),
#                 message={
#                     "type": evt_map(type),
#                     "address": data.get("addr", 0),
#                     "key": data.get("key", -1),
#                     "duration": data.get("duration", 1),
#                 },
#             )

#             return True

#         return False

#     async def set_key_colour(self, key: int, rgb: list[int]) -> None:
#         await self.send_request(
#             req=self.MSG_SET_COLOUR,
#             data={
#                 "id": self.id,
#                 "key": key,
#                 "rgb": rgb
#             }
#         )


class TagoWebsocketClient:
    MESSAGE = 'msg'
    CONNECTION = 'connection'

    def __init__(self, uri: str, ca: str = None, pin: str = list()):
        self._uri = uri
        self._ca = ca
        self._pin = pin
        self._ws = None
        self._task = None
        self._running: bool = False
        self._handlers: dict = {
            self.MESSAGE: list(), self.CONNECTION: list()}
        self._connected_flag = asyncio.Event()
        self._disconnected_flag = asyncio.Event()

    @property
    def uri(self):
        return self._uri

    def subscribe(self, _type: str, cb: Callable) -> None:
        self._handlers[_type].append(cb)
        self._handlers[_type] = list(set(self._handlers[_type]))

    def unsubscribe(self, _type: str, cb: Callable) -> None:
        if cb in self._handlers[_type]:
            self._handlers[_type].remove(cb)

    async def _notify(self, _type: str, *args, **kwargs) -> None:
        for cb in self._handlers[_type]:
            try:
                await cb(*args, **kwargs)
            except Exception as err:
                _LOGGER.exception(err)

    def set_ca(self, ca: str) -> None:
        self._ca = ca

    def set_pin(self, _pin: list[str]) -> None:
        self.pin = _pin

    async def connect(self, timeout: float | None = None) -> None:
        if self.is_connected() or self._running:
            return

        self._running = True
        self._task = asyncio.create_task(self.connection_task())

        if timeout is None:
            await self._connected_flag.wait()
        else:
            try:
                async with asyncio.timeout(timeout):
                    await self._connected_flag.wait()
            except asyncio.TimeoutError:
                self._running = False
                raise

    async def disconnect(self, timeout: float | None = None, only_if_last: bool = False) -> None:
        print('disconnect -- attempt ')
        # If only_if_last flag is set, then disconnect if no event subscribes remain
        if only_if_last and len(self._handlers[self.CONNECTION]) > 0:
            return
        print('disconnect -- ')
        self._running = False
        if self._ws:
            await self._ws.close()

        if timeout is None:
            await self._disconnected_flag.wait()
        else:
            try:
                async with asyncio.timeout(timeout):
                    await self._disconnected_flag.wait()

            except TimeoutError:
                self._task.cancel()
            finally:
                self._task = None

        self._task = None

    def is_connected(self) -> bool:
        return self._connected_flag.is_set()

    @staticmethod
    def create_random_str(n: int = 6) -> str:
        return ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(n))

    async def send_request(self, data: dict = None, responseTimeout: float = None) -> None | TagoMessage:
        """ sends a message to peer, and optionally waits for a response to be received or a timeout to occur. """
        resp: TagoMessage = None
        flag = asyncio.Event()

        ref = self.create_random_str()
        data['ref'] = ref

        if self._pin:
            data['pin'] = self._pin

        if responseTimeout:
            async def check_response(msg: TagoMessage):
                nonlocal resp
                if msg.refers_to(ref):
                    resp = msg
                    flag.set()

            self.subscribe(self.MESSAGE, check_response)

        try:
            payload = json.dumps(data)
            _LOGGER.debug(f"=== send_request {payload}")
            await self._ws.send(payload)
            if responseTimeout:
                async with asyncio.timeout(responseTimeout):
                    await flag.wait()
                    return resp
        finally:
            if responseTimeout:
                self.unsubscribe(self.MESSAGE, check_response)

    async def connection_task(self) -> None:
        def _create_context(_ca: str) -> ssl.SSLContext:
            try:
                ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                ssl_context.check_hostname = False
                if _ca:
                    ssl_context.load_verify_locations(cadata=_ca)
                    ssl_context.verify_mode = ssl.CERT_REQUIRED
                else:
                    ssl_context.verify_mode = ssl.CERT_NONE

                return ssl_context
            except Exception as e:
                _LOGGER.exception(e)

        ssl_context = await asyncio.get_running_loop().run_in_executor(
            None, _create_context, self._ca
        )

        self._running = True
        while self._running:
            _LOGGER.debug(f"connecting to {self._uri}")
            try:
                async with wsconnect(
                    uri=self._uri, ping_timeout=1, ping_interval=3,
                    ssl=ssl_context,
                    additional_headers={"X-Authorization-PIN": self._pin}
                ) as ws:
                    self._ws = ws
                    _LOGGER.debug(f"connected to {self._uri}")

                    # notify connection
                    self._disconnected_flag.clear()
                    self._connected_flag.set()
                    await self._notify(self.CONNECTION, True)

                    async for message in ws:
                        await self._notify(self.MESSAGE, TagoMessage(message))
            except Exception as e:
                self._ws = None
                # _LOGGER.exception(e)

            # notify disconnection
            if self._connected_flag.is_set():
                self._connected_flag.clear()
                self._disconnected_flag.set()
                await self._notify(self.CONNECTION, False)

            # small delay between successive attempts to connect
            if self._running:
                await asyncio.sleep(1)


class TagoController(TagoWebsocketClient):
    CONTROLLER_ID = "controller"
    REQ_TEST_LINK = "test_link"
    REQ_LIST_NODES = "list_nodes"

    async def list_nodes(self, timeout=2):
        msg = await self.send_request(TagoMessage.request(req=self.REQ_LIST_NODES, dst=self.CONTROLLER_ID), timeout)
        nodes = msg.content.get('nodes', list())
        return nodes

    # async def test_link(self, timeout=2):
    #     msg = await self.send_request({'req': self.REQ_TEST_LINK}, timeout)
    #     return {
    #         'uri': msg.get('uri'),
    #         'ca': msg.get('ca_cert'),
    #         'pin': msg.get('pin'),
    #         'network_id': msg.get('network_id'),
    #         'network_name': msg.get('network_name')
    #     }


def entities_from_nodes(nodes: list) -> list[TagoEntityHA]:
    ws: dict[str: TagoWebsocketClient] = dict()
    for n in nodes:
        uri = n['uri']
        if uri in ws:
            continue
        ws[uri] = TagoWebsocketClient(uri=uri)

    ents: list[TagoEntityHA] = list()
    for n in nodes:
        type = n['type']
        if type in TagoLightHA.types:
            ent: TagoLightHA = TagoLightHA(json=n)
        elif type in TagoFanHA.types:
            ent: TagoFanHA = TagoFanHA(json=n)
        elif type in TagoCoverHA.types:
            ent: TagoCoverHA = TagoCoverHA(json=n)
        elif type in TagoSwitchHA.types:
            ent: TagoSwitchHA = TagoSwitchHA(json=n)
        elif type in TagoKeypadHA.types:
            ent: TagoKeypadHA = TagoKeypadHA(json=n)
        else:
            ent: TagoEntityHA = TagoEntityHA(json=n)

        ent.set_api(ws[n['uri']])
        ents.append(ent)

    return ents
