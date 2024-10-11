from __future__ import annotations

import asyncio
from collections.abc import Callable
import json
import logging
import math

import websockets

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

_LOGGER = logging.getLogger(__name__)

class TagoConnection:
    def __init__(self, hostname: str, network_key: str):
        self._host = hostname
        self._netkey = network_key
        self._connect_attempt = 0

        self._ws = None
        self._enumerated = False
        self._task = None
        self._running = False

        self.devices = []

    async def connect(self, timeout: float = None) -> None:
        if not self._task:
            self._task = asyncio.create_task(self.connection_task())

        ## If timeout is set, block until the device is enumerated or we've failed to connect
        if timeout is None:
            return

        async with asyncio.timeout(timeout):
            while not self._enumerated:
                await asyncio.sleep(0.5)

    async def disconnect(self) -> None:
        self._running = False
        if self._ws:
            await self._ws.close()

        try:
            async with asyncio.timeout(2):
                while self.is_connected:
                    await asyncio.sleep(0.5)
        except TimeoutError:
            self._task.cancel()
        self._task = None

    def is_connected(self) -> bool:
        return self._ws is not None

    async def send_message(self, data: dict) -> None:
        payload = json.dumps(data)
        _LOGGER.debug(f"=== send_message {payload}")
        self._ws.send(payload)

    async def list_devices(self) -> None:
        await self.send_message(msg=self.MSG_GET_DEVICES)

    async def connection_task(self) -> None:
        self._connect_attempt = 0
        uri = f"ws://{self._host}/api/v1/ws"
        self._running = True
        while self._running:
            _LOGGER.debug(f"connecting to {self._host}")
            try:
                async with websockets.connect(
                    uri=uri, ping_timeout=1, ping_interval=3
                ) as websocket:
                    self._ws = websocket
                    self._connect_attempt = 0
                    _LOGGER.info(f"connected to {self._host}")
                    try:
                        if not self._enumerated:
                            await self.list_devices()

                        for message in self._ws:
                            msg = json.loads(message)
                            if msg['msg'] == self.MSG_GET_DEVICES:
                                ## handle deviecs
                                pass
                            else:
                                for device in self.devices:
                                    device.handle_message(msg)

                    except Exception:
                        self._ws = None
                        self.updated()
                        # _LOGGER.info("==== EXCEPT")
                        # _LOGGER.exception(e)
            except Exception:
                self._ws = None
                self._connect_attempt = self._connect_attempt + 1
                self.updated()
                # _LOGGER.exception(e)
            ## small delay between successive attempts to connect
            if self._running:
                await asyncio.sleep(0.5)

class TagoEntity:
    EVT_STATE_CHANGED = "state_changed"
    EVT_CONFIG_CHANGED = "config_changed"
    EVT_KEYPRESS = "key_press"
    EVT_KEYRELEASE = "key_release"

    MSG_GET_DEVICES = "get_devices"
    MSG_SET_CONFIG = "set_config"
    MSG_GET_STATE  = "get_state"
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
        ## TODO -- extrapolate from channel type
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

class TagoBridge(TagoEntity):
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

class TagoLightHA(TagoEntity, LightEntity):
    LIGHT_ONOFF = "light_onoff"
    LIGHT_MONO = "light"
    LIGHT_RGB = "light_rgb"
    LIGHT_RGBW = "light_rgbw"
    LIGHT_RGB_CCT = "light_rgbww"
    LIGHT_CCT = "light_ww"

    types = [LIGHT_ONOFF, LIGHT_MONO, LIGHT_RGB, LIGHT_RGBW, LIGHT_RGB_CCT, LIGHT_CCT]

    STATE_ON = "on"
    STATE_OFF = "off"

    def __init__(self, type: str, data: dict, device: TagoDevice):
        super().__init__(data, device)

        self._type = type
        self._id = data.get("id")
        self._state = data.get("state", self.STATE_OFF)
        ## TODO default intensities based on type
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

        ## TODO handle multicoloured lights
        data = {
            "intensity": [brightness],
        }

        if transition_time is not None:
            data["rate"] = int((TagoEntity.RANGE_MAX * 6) / (int(transition_time * 1000)))

        await self.send_message(
            msg=self.MSG_FADE_TO, data=data
        )

    async def async_turn_off(self, **kwargs):
        await self.send_message(msg=self.MSG_TURN_OFF)

    @staticmethod
    def convert_intensity_to_device(
        intensity: float, srclimit: float = 255
    ) -> int:
        return int(round((intensity * TagoEntity.RANGE_MAX) / srclimit, 0))

    @staticmethod
    def convert_intensity_from_device(
        intensity: float, srclimit: float = 255
    ) -> int:
        return int(round((intensity * srclimit) / TagoEntity.RANGE_MAX, 0))

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

class TagoFanHA(TagoEntity, FanEntity):
    FAN_ONOFF = "fan_onoff"
    FAN_ADJUSTABLE = "fan"

    types = [FAN_ONOFF, FAN_ADJUSTABLE]

    STATE_ON = "on"
    STATE_OFF = "off"

    SPEED_RANGE = (0, TagoEntity.RANGE_MAX)

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

        level = math.ceil(percentage_to_ranged_value(self.SPEED_RANGE, percentage))
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
            ## TODO -- how to handle type change from fan to light??
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

class TagoDevice:
    def __init__(self, conn: TagoConnection):
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
        if model == 'DM8B' :
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
                ## Device enumeration
                case self.MSG_GET_STATE:
                    self._id = msg["id"]
                    self._name = msg.get("name", 'TAGO Device')
                    self.fw_rev = msg.get("firmware_rev", '')
                    self.model_name = msg.get("model_name", 'Unknown')
                    self.model_desc = msg.get("model_desc", 'Unknown')
                    self.serial_number = msg.get("serial_number", 'Unknown')

                    ## handle modules

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
