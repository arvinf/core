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

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_TRANSITION,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.util.percentage import (
    percentage_to_ranged_value,
    ranged_value_to_percentage,
)

import tempfile

_LOGGER = logging.getLogger(__name__)


class TagoEntityHA:
    EVT_STATE_CHANGED = "state_changed"
    EVT_CONFIG_CHANGED = "config_changed"
    EVT_KEYPRESS = "key_press"
    EVT_KEYRELEASE = "key_release"

    MSG_GET_DEVICES = "get_devices"
    MSG_SET_CONFIG = "set_config"
    MSG_GET_STATE = "get_state"
    MSG_TURN_ON = "turn_on"
    MSG_TURN_OFF = "turn_off"
    MSG_TOGGLE = "toggle"
    MSG_FADE_TO = "fade_to"
    MSG_MOVE_TO = "move_to"
    MSG_SET_COLOUR = "set_colour"

    MSG_IDENTIFY = "device_identify"
    MSG_REBOOT = "device_reboot"
    MSG_ERROR = "error"

    TYPE_MODBUS = "modbus"
    TYPE_DIMMER_AC = "dimmer_ac"
    TYPE_DIMMER_0to10V = "dimmer_10v"
    TYPE_LED_DRIVER = "led_driver"
    TYPE_RELAY = "relay"
    TYPE_CURTAINS = "curtains"
    TYPE_KEYPAD = "keypad"

    RANGE_MAX = 65535

    def __init__(self, data: dict[str, str], device: object):
        self._uid = data["id"]
        self._name = data.get("name", "Unnamed")
        self._area = data.get("area", "unassigned")
        self._device = device

    @property
    def type(self) -> str:
        # TODO -- extrapolate from channel type
        p = self._uid.split(":")
        if len(p) > 2:
            return p[1]
        return p[0]

    def updated(self) -> None:
        self.schedule_update_ha_state()

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
        return self.device().is_connected

    async def send_message(self, msg: str, data: object = {}) -> None:
        data['id'] = self._uid
        data['msg'] = msg
        await self._conn.send_message(data)

    def handle_message(self, type: str, data: dict[str, str]) -> bool:
        if type == self.EVT_CONFIG_CHANGED:
            self._name = data.get("name", self._name)
            return True

        return False


class TagoBridge(TagoEntityHA):
    def __init__(self, data: dict[str, str], device: TagoDevice):
        super().__init__(data, device)
        self._message_handler = None

    def set_message_handler(
        self, handler: Callable[[TagoBridge, str, dict[str, str]]]
    ) -> None:
        self._message_handler = handler

    def forward_message(self, entity_id: str, message: dict[str, str]) -> None:
        if self._message_handler is None:
            return

        self._message_handler(self, entity_id=entity_id, message=message)


class TagoLightHA(TagoEntityHA, LightEntity):
    LIGHT_ONOFF = "light_onoff"
    LIGHT_MONO = "light"
    LIGHT_RGB = "light_rgb"
    LIGHT_RGBW = "light_rgbw"
    LIGHT_RGB_CCT = "light_rgbww"
    LIGHT_CCT = "light_ww"

    types = [LIGHT_ONOFF, LIGHT_MONO, LIGHT_RGB,
             LIGHT_RGBW, LIGHT_RGB_CCT, LIGHT_CCT]

    STATE_ON = "on"
    STATE_OFF = "off"

    def __init__(self, type: str, data: dict, device: TagoDevice):
        super().__init__(data, device)

        self._type = type
        self._id = data.get("id")
        self._state = data.get("state", self.STATE_OFF)
        # TODO default intensities based on type
        self._intensity = data.get("intensity", [0])

    @property
    def is_dimmable(self):
        return self.type != self.LIGHT_ONOFF

    @property
    def is_on(self):
        return self._state == self.STATE_ON and self._intensity > 0

    @property
    def supported_features(self) -> int | None:
        return LightEntityFeature.TRANSITION if self.is_dimmable else 0

    @property
    def color_mode(self):
        return ColorMode.BRIGHTNESS if self.is_dimmable else ColorMode.ONOFF

    @property
    def supported_color_modes(self) -> set[ColorMode] | set[str] | None:
        return (
            {ColorMode.BRIGHTNESS}
            if self.is_dimmable
            else {ColorMode.ONOFF}
        )

    @property
    def brightness(self) -> int:
        return self.convert_intensity_from_device(self._intensity)

    async def async_turn_on(self, **kwargs):
        brightness = self.convert_intensity_to_device(
            kwargs.pop(ATTR_BRIGHTNESS, 255)
        )
        if ATTR_TRANSITION in kwargs:
            transition_time = kwargs[ATTR_TRANSITION]
        else:
            transition_time = 0.5

        # TODO handle multicoloured lights
        data = {
            "intensity": [brightness],
        }

        if transition_time is not None:
            data["rate"] = int((TagoEntityHA.RANGE_MAX * 6) /
                               (int(transition_time * 1000)))

        await self.send_message(
            msg=self.MSG_FADE_TO, data=data
        )

    async def async_turn_off(self, **kwargs):
        await self.send_message(msg=self.MSG_TURN_OFF)

    @staticmethod
    def convert_intensity_to_device(
        intensity: float, srclimit: float = 255
    ) -> int:
        return int(round((intensity * TagoEntityHA.RANGE_MAX) / srclimit, 0))

    @staticmethod
    def convert_intensity_from_device(
        intensity: float, srclimit: float = 255
    ) -> int:
        return int(round((intensity * srclimit) / TagoEntityHA.RANGE_MAX, 0))

    def handle_message(self, type: str, data: dict[str, str]) -> bool:
        super().handle_message(type=type, data=data)
        if type == self.EVT_STATE_CHANGED:
            self._intensity = data.get("intensity", self._intensity)
            self._state = data.get("state", self._state)
            return True

        if type == self.EVT_CONFIG_CHANGED:
            self._name = data.get("name", self._name)
            self._type = data.get("type", self._type)
            return True

        return False


class TagoFanHA(TagoEntityHA, FanEntity):
    FAN_ONOFF = "fan_onoff"
    FAN_ADJUSTABLE = "fan"

    types = [FAN_ONOFF, FAN_ADJUSTABLE]

    STATE_ON = "on"
    STATE_OFF = "off"

    SPEED_RANGE = (0, TagoEntityHA.RANGE_MAX)

    def __init__(self, type: str, data: dict, device: TagoDevice):
        super().__init__(data, device)
        self._type = type
        self._intensity = data.get('intensity', [0])
        self._id = data.get("id")
        self._state = data.get("state", self.STATE_OFF)

        print('FAN created', self.unique_id)

    @property
    def is_on(self):
        return self._state == self.STATE_ON

    @property
    def supported_features(self) -> int | None:
        return FanEntityFeature.TURN_ON | FanEntityFeature.TURN_OFF if self._type == self.FAN_ONOFF else FanEntityFeature.TURN_ON | FanEntityFeature.TURN_OFF | FanEntityFeature.SET_SPEED

    @property
    def percentage(self) -> int | None:
        return ranged_value_to_percentage(self.SPEED_RANGE, self._intensity[0])

    async def async_turn_on(
        self,
        percentage: int | None = None,
        **kwargs,
    ) -> None:
        if (percentage):
            return self.async_set_percentage(percentage)

        await self.send_message(msg=self.MSG_TURN_ON)

    async def async_turn_off(self, **kwargs):
        await self.send_message(msg=self.MSG_TURN_OFF)

    async def async_set_percentage(self, percentage: int) -> None:
        if percentage == 0:
            await self.async_turn_off()
            return

        level = math.ceil(percentage_to_ranged_value(
            self.SPEED_RANGE, percentage))
        await self.send_message(
            msg=self.MSG_FADE_TO, data={"intensity": [level]}
        )

    def handle_message(self, type: str, data: dict[str, str]) -> bool:
        super().handle_message(type=type, data=data)
        if type == self.EVT_STATE_CHANGED:
            self._intensity = data.get("intensity", self._intensity)
            self._state = data.get("state", self._state)
            return True

        if type == self.EVT_CONFIG_CHANGED:
            self._name = data.get("name", self._name)
            # TODO -- how to handle type change from fan to light??
            self._type = data.get("type", self._type)
            return True

        return False


class TagoKeypad(TagoBridge):
    def handle_message(self, type: str, data: dict[str, str]) -> bool:
        super().handle_message(type=type, data=data)
        evt_map = {
            self.EVT_KEYRELEASE: 'key_release',
            self.EVT_KEYPRESS: 'keypress'
        }

        if type in evt_map:
            self.forward_message(
                entity_id=data.get("id", ""),
                message={
                    "type": evt_map(type),
                    "address": data.get("addr", 0),
                    "key": data.get("key", -1),
                    "duration": data.get("duration", 1),
                },
            )

            return True

        return False

    async def set_key_colour(self, key: int, rgb: list[int]) -> None:
        await self.send_message(
            msg=self.MSG_SET_COLOUR,
            data={
                "id": self.id,
                "key": key,
                "rgb": rgb
            }
        )


class TagoWebsocketClient:
    MSG_EVT = 'msg'
    CONNECTION_EVT = 'connection'

    def __init__(self, uri: str, ca: str, pin: str):
        self._uri = uri
        self._ca = ca
        self._pin = pin
        self._ws = None
        self._task = None
        self._running: bool = False
        self._handlers: dict = {
            self.MSG_EVT: list(), self.CONNECTION_EVT: list()}
        self._connected_flag = asyncio.Event()
        self._disconnected_flag = asyncio.Event()

    def subscribe(self, _type: str, cb: Callable) -> None:
        self._handlers[_type].append(cb)

    def unsubscribe(self, _type: str, cb: Callable) -> None:
        if cb in self._handlers[_type]:
            self._handlers[_type].remove(cb)

    def _notify(self, _type: str, *args, **kwargs) -> None:
        for cb in self._handlers[_type]:
            cb(*args, **kwargs)

    def set_ca(self, _ca: str) -> None:
        self.ca = _ca

    @property
    def uri(self):
        return self._uri

    async def connect(self, timeout: float = 3) -> None:
        if self.is_connected():
            return

        self._task = asyncio.create_task(self.connection_task())

        try:
            async with asyncio.timeout(timeout):
                await self._connected_flag.wait()
        except asyncio.TimeoutError:
            self._running = False
            raise

    async def disconnect(self, timeout: float = 3) -> None:
        self._running = False
        if self._ws:
            await self._ws.close()
        try:
            async with asyncio.timeout(timeout):
                await self._disconnected_flag.wait()

        except TimeoutError:
            self._task.cancel()
        finally:
            self._task = None

    def is_connected(self) -> bool:
        return self._connected_flag.is_set()

    @staticmethod
    def create_random_str(n: int = 6) -> str:
        return ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(n))

    async def send_message(self, data: dict, responseTimeout: float = None) -> None | dict:
        resp: dict = None
        flag = asyncio.Event()

        if responseTimeout:
            ref = self.create_random_str()
            data['ref'] = ref

            def check_response(msg: dict):
                nonlocal resp
                if msg.get('ref') == ref:
                    resp = msg
                    flag.set()

            self.subscribe(self.MSG_EVT, check_response)

        try:
            if self._pin:
                data['pin'] = self._pin
            payload = json.dumps(data)
            _LOGGER.debug(f"=== send_message {payload}")
            await self._ws.send(payload)
            if responseTimeout:
                async with asyncio.timeout(responseTimeout):
                    await flag.wait()
                    return resp
        finally:
            self.unsubscribe(self.MSG_EVT, check_response)

    async def connection_task(self) -> None:
        def _create_context(_ca: str) -> ssl.SSLContext:
            try:
                ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                if _ca:
                    ssl_context.load_verify_locations(cadata=_ca)
                    ssl_context.verify_mode = ssl.CERT_REQUIRED
                else:
                    ssl_context.verify_mode = ssl.CERT_NONE
                ssl_context.check_hostname = False

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
                    additional_headers={"X-Authorization": f'PIN-{self._pin}'}
                ) as ws:
                    self._ws = ws
                    _LOGGER.info(f"connected to {self._uri}")

                    # notify connection
                    self._disconnected_flag.clear()
                    self._connected_flag.set()
                    self._notify('connection', True)

                    async for message in ws:
                        msg = json.loads(message)
                        self._notify(self.MSG_EVT, msg)
            except Exception as e:
                self._ws = None
                # _LOGGER.exception(e)

            # notify disconnection
            if self._connected_flag.is_set():
                self._connected_flag.clear()
                self._disconnected_flag.set()
                self._notify('connection', False)

            # small delay between successive attempts to connect
            if self._running:
                await asyncio.sleep(0.5)


class TagoGateway(TagoWebsocketClient):
    REQ_LIST_DEVICES        = "req_list_devices"
    async def list_devices(self) -> None:
        return await self.send_message({'msg': self.REQ_LIST_DEVICES}, 2)


class TagoController(TagoWebsocketClient):
    REQ_TEST_LINK = "req_test_link"
    REQ_LIST_NODES = "req_list_nodes"

    async def list_nodes(self, timeout=2):
        msg = await self.send_message({'msg': self.REQ_LIST_NODES}, timeout)
        return msg['nodes']

    async def test_link(self, timeout=2):
        msg = await self.send_message({'msg': self.REQ_TEST_LINK}, timeout)
        return {
            'uri': msg.get('uri'),
            'ca': msg.get('ca_cert'),
            'pin': msg.get('pin'),
            'network_id': msg.get('network_id'),
            'network_name': msg.get('network_name')
        }


class TagoDevice:
    def __init__(self, conn: TagoGateway):
        super().__init__({}, conn)
        self._uid: str = ''
        self._name: str = ''

        self._keypads: list = list()
        self._curtains: list = list()
        self._dimmer_ac: list = list()
        self._led_driver: list = list()
        self._children: dict[str, object] = {}

        self.fw_rev: str = None
        self.model_name: str = None
        self.model_desc: str = None
        self.serial_number: str = None
        self.manufacturer: str = "Tago"

    @property
    def uid(self) -> str:
        return self._uid

    @property
    def name(self) -> str:
        return self._name

    @property
    def is_connected(self) -> bool:
        return self._conn.is_connected()

    @property
    def lights(self) -> list:
        return self._lights

    @property
    def bridges(self) -> list:
        return self._keypads

    @property
    def is_enumerated(self) -> bool:
        return self._enumerated

    @property
    def host(self) -> str:
        return self._host

    @staticmethod
    def model_num_to_desc(model: str) -> str:
        """convert model number to string"""
        if model == 'DM8B':
            return 'DIN 8 Channel AC Dimmer'
        return 'Unknown'

    def updated(self) -> None:
        for uid in self._children:
            self._children[uid].updated()

    async def send_message(self, msg: str, data: object = {}, id: str = None) -> None:
        data["msg"] = msg
        if id is None:
            data["id"] = self.id
        else:
            data["id"] = id

        await self._conn.send_message(data)

    async def get_device_info(self) -> None:
        await self.send_message(msg=self.MSG_DEVICE_GET_INFO)

    def message_is_for_me(self, msg: object) -> bool:
        uid = msg['id']
        return (uid == self.uid)

    def message_is_for_children(self, msg: object) -> bool:
        uid = msg['id'].split(':')
        return (len(uid) > 1 and uid[0] == self._uid)

    def handle_message(self, msg: object) -> None:
        if self.message_is_for_children(msg):
            child = self._children.get(uid, None)
            if child and child.handle_message(type=msg["msg"], data=msg):
                child.updated()

        if self.message_is_for_me(msg):
            _LOGGER.debug(f"=== process_device_msg {msg}")
            match msg["msg"]:
                # Device enumeration
                case self.MSG_GET_STATE:
                    self._id = msg["id"]
                    self._name = msg.get("name", 'TAGO Device')
                    self.fw_rev = msg.get("firmware_rev", '')
                    self.model_name = msg.get("model_name", 'Unknown')
                    self.model_desc = msg.get("model_desc", 'Unknown')
                    self.serial_number = msg.get("serial_number", 'Unknown')

                    # handle modules

                    # # Create a child for every enabled output channel on the device
                    # for item in msg.get(self.TYPE_DIMMER_AC, []):
                    #     child = None

                    #     # print('light type', item.get('type'))
                    #     if item.get("type") in TagoLight.types:
                    #         child = TagoLight(item, self)
                    #         self._lights.append(child)
                    #     else:
                    #         _LOGGER.error(f"unsupported item {item}")

                    #     if child:
                    #         self._children[child.uid] = child

                    # for item in msg.get(self.TYPE_MODBUS, []):
                    #     child = TagoKeypad(item, self)
                    #     self._keypads.append(child)
                    #     self._children[child.uid] = child

                    self._enumerated = True

                case self.MSG_ERROR:
                    _LOGGER.error(f"command failed {msg}")
                case _:
                    _LOGGER.error(f"unsupported message {msg}.")

    async def identify(self) -> None:
        await self.send_message(msg=self.MSG_IDENTIFY)

    async def reboot(self) -> None:
        await self.send_message(msg=self.MSG_REBOOT)
