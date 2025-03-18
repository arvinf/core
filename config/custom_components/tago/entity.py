from .TagoNet import TagoEntity, TagoDevice
import json
from homeassistant.helpers.entity import DeviceInfo
from .const import (
    DOMAIN,
)

class TagoEntityHA:
    MAX_VALUE = 10000

    def __init__(self, entity: TagoEntity):
        self._entity: TagoEntity = entity
        self._entity.set_on_state_changed(self.on_state_updated)        

        # if len(self._location.strip()):
        #     info[ATTR_SUGGESTED_AREA] = self._location
        #     self._attr_device_info = self._entity.device.get_info()

    def on_state_updated(self):
        self.update()

    def __repr__(self):
        return json.dumps({
            'id': self._uid,
            'name': self.name,
            'location': self._location,
            'type': self._type,
            'connected': self.available
        }, indent=2)

    def is_of_domain(self, domain: str) -> bool:
        return False

    def update(self) -> None:
        self.schedule_update_ha_state()

    @property
    def type(self) -> str:
        return self._entity.type or 'UNUSED'

    @property
    def should_poll(self) -> bool:
        return False

    @property
    def has_entity_name(self) -> bool:
        return False
        return (self._entity.name is not None)

    @property
    def name(self) -> str:
        """Name"""
        return self._entity.name or 'Unnamed'
    
    @property
    def unique_id(self) -> str:
        """Unique id"""
        return self._entity.unique_id

    @property
    def available(self) -> bool:
        """Available"""
        return self._entity.is_connected

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entity._device.unique_id)},
            name=self._entity._device.name,
            manufacturer=self._entity._device.manufacturer,
            model=self._entity._device.model_num,
            configuration_url=self._entity._device.dashboard_uri,
        )
        
            
    @staticmethod
    def convert_value_to_device(
        intensity: float, srclimit: float = 255
    ) -> float:
        return (intensity / srclimit)

    @staticmethod
    def convert_value_from_device(
        intensity: float, srclimit: float = 255
    ) -> int:
        return int(round((intensity * srclimit), 0))
