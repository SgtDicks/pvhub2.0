"""PVHub 2.0 Readonly sensors."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_PLANT_ID, DOMAIN
from .coordinator import PVHubDataUpdateCoordinator


@dataclass(frozen=True, kw_only=True)
class PVHubSensorEntityDescription(SensorEntityDescription):
    """PVHub sensor description."""

    source_key: str
    device_key: str
    device_name: str
    device_model: str


SENSORS: tuple[PVHubSensorEntityDescription, ...] = (
    PVHubSensorEntityDescription(
        key="battery_soc",
        translation_key="battery_soc",
        source_key="battery_soc_percent",
        device_key="battery",
        device_name="PVHub Battery",
        device_model="PVHub Battery",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    PVHubSensorEntityDescription(
        key="solar_power",
        translation_key="solar_power",
        source_key="pv_power_kw",
        device_key="solar",
        device_name="PVHub Solar Inverter",
        device_model="PVHub Solar / Inverter",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    PVHubSensorEntityDescription(
        key="battery_charge_power",
        translation_key="battery_charge_power",
        source_key="battery_charge_power_kw",
        device_key="battery",
        device_name="PVHub Battery",
        device_model="PVHub Battery",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    PVHubSensorEntityDescription(
        key="battery_discharge_power",
        translation_key="battery_discharge_power",
        source_key="battery_discharge_power_kw",
        device_key="battery",
        device_name="PVHub Battery",
        device_model="PVHub Battery",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    PVHubSensorEntityDescription(
        key="grid_export_power",
        translation_key="grid_export_power",
        source_key="grid_export_power_kw",
        device_key="grid",
        device_name="PVHub Grid Meter",
        device_model="PVHub Meter",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    PVHubSensorEntityDescription(
        key="grid_import_power",
        translation_key="grid_import_power",
        source_key="grid_import_power_kw",
        device_key="grid",
        device_name="PVHub Grid Meter",
        device_model="PVHub Meter",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    PVHubSensorEntityDescription(
        key="load_power",
        translation_key="load_power",
        source_key="load_power_kw",
        device_key="load",
        device_name="PVHub Site Load",
        device_model="PVHub Load",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up PVHub sensors."""

    coordinator: PVHubDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(PVHubSensor(coordinator, entry, description) for description in SENSORS)


class PVHubSensor(CoordinatorEntity[PVHubDataUpdateCoordinator], SensorEntity):
    """PVHub sensor entity."""

    entity_description: PVHubSensorEntityDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: PVHubDataUpdateCoordinator,
        entry: ConfigEntry,
        description: PVHubSensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        plant_id = entry.data[CONF_PLANT_ID]
        self._attr_unique_id = f"{plant_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{plant_id}_{description.device_key}")},
            configuration_url="https://www.pv-hub.com/v2/plants/analysis",
            manufacturer="PVHub",
            name=description.device_name,
            model=description.device_model,
        )

    @property
    def native_value(self) -> float | None:
        """Return latest sensor value."""

        value = self.coordinator.data.get(self.entity_description.source_key)
        return value if isinstance(value, int | float) else None

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Return raw/display timestamp attributes."""

        key = self.entity_description.source_key
        attrs: dict[str, object] = {}
        for suffix in ("raw", "display", "time"):
            attr_key = f"{key}_{suffix}"
            if attr_key in self.coordinator.data:
                attrs[suffix] = self.coordinator.data[attr_key]
        if "updated_at" in self.coordinator.data:
            attrs["updated_at"] = self.coordinator.data["updated_at"]
        return attrs
