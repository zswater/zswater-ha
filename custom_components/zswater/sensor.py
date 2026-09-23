"""Sensors for the Zhongshan Water integration.

Entities are declared once in :data:`_SENSOR_DEFINITIONS` rather than built up
in the constructor: adding a sensor means adding one table row plus its
translation keys, and the platform code never changes.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_KEY_ACCOUNT_STATUS,
    ATTR_KEY_ADDRESS,
    ATTR_KEY_HISTORY,
    ATTR_KEY_IS_TIERED,
    ATTR_KEY_METER_NAME,
    ATTR_KEY_METER_NUMBER,
    ATTR_KEY_TIER1_REMAINING,
    ATTR_KEY_TIER2_REMAINING,
    CONF_WATER_ACCOUNTS,
    DOMAIN,
    SUFFIX_ARREARS,
    SUFFIX_BALANCE,
    SUFFIX_CURRENT_BILL,
    SUFFIX_CURRENT_READ_DATE,
    SUFFIX_CURRENT_READING,
    SUFFIX_HISTORY,
    SUFFIX_LAST_READING,
    SUFFIX_LAST_READ_DATE,
    SUFFIX_PAYABLE,
    SUFFIX_PENALTY,
    SUFFIX_USAGE,
    SUFFIX_WATER_FEE,
)
from .coordinator import ZSWaterCoordinator
from .zswater_client import MeterSnapshot

CURRENCY_CNY = "CNY"


def _as_date(value: str | None) -> date | None:
    """Convert an already-normalised ``YYYY-MM-DD`` string to ``date``."""
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


@dataclass(frozen=True, kw_only=True)
class ZSWaterSensorDefinition(SensorEntityDescription):
    """A sensor plus the snapshot accessor that fills it."""

    value_fn: Callable[[MeterSnapshot], Any]


_SENSOR_DEFINITIONS: tuple[ZSWaterSensorDefinition, ...] = (
    ZSWaterSensorDefinition(
        key=SUFFIX_ARREARS,
        translation_key=SUFFIX_ARREARS,
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=CURRENCY_CNY,
        icon="mdi:water-alert",
        value_fn=lambda snap: snap.arrears,
    ),
    ZSWaterSensorDefinition(
        key=SUFFIX_CURRENT_BILL,
        translation_key=SUFFIX_CURRENT_BILL,
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=CURRENCY_CNY,
        icon="mdi:file-document-outline",
        value_fn=lambda snap: snap.current_bill,
    ),
    ZSWaterSensorDefinition(
        key=SUFFIX_BALANCE,
        translation_key=SUFFIX_BALANCE,
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=CURRENCY_CNY,
        icon="mdi:wallet",
        value_fn=lambda snap: snap.balance,
    ),
    ZSWaterSensorDefinition(
        key=SUFFIX_LAST_READING,
        translation_key=SUFFIX_LAST_READING,
        device_class=SensorDeviceClass.WATER,
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:counter",
        value_fn=lambda snap: snap.last_reading,
    ),
    ZSWaterSensorDefinition(
        key=SUFFIX_CURRENT_READING,
        translation_key=SUFFIX_CURRENT_READING,
        device_class=SensorDeviceClass.WATER,
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:gauge",
        value_fn=lambda snap: snap.current_reading,
    ),
    ZSWaterSensorDefinition(
        key=SUFFIX_USAGE,
        translation_key=SUFFIX_USAGE,
        device_class=SensorDeviceClass.WATER,
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:water",
        value_fn=lambda snap: snap.usage,
    ),
    ZSWaterSensorDefinition(
        key=SUFFIX_WATER_FEE,
        translation_key=SUFFIX_WATER_FEE,
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=CURRENCY_CNY,
        icon="mdi:currency-cny",
        value_fn=lambda snap: snap.water_fee,
    ),
    ZSWaterSensorDefinition(
        key=SUFFIX_PENALTY,
        translation_key=SUFFIX_PENALTY,
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=CURRENCY_CNY,
        icon="mdi:alert-octagon-outline",
        value_fn=lambda snap: snap.penalty,
    ),
    ZSWaterSensorDefinition(
        key=SUFFIX_PAYABLE,
        translation_key=SUFFIX_PAYABLE,
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=CURRENCY_CNY,
        icon="mdi:cash",
        value_fn=lambda snap: snap.payable,
    ),
    ZSWaterSensorDefinition(
        key=SUFFIX_LAST_READ_DATE,
        translation_key=SUFFIX_LAST_READ_DATE,
        device_class=SensorDeviceClass.DATE,
        icon="mdi:calendar-arrow-left",
        value_fn=lambda snap: _as_date(snap.last_read_date),
    ),
    ZSWaterSensorDefinition(
        key=SUFFIX_CURRENT_READ_DATE,
        translation_key=SUFFIX_CURRENT_READ_DATE,
        device_class=SensorDeviceClass.DATE,
        icon="mdi:calendar-check",
        value_fn=lambda snap: _as_date(snap.current_read_date),
    ),
    ZSWaterSensorDefinition(
        key=SUFFIX_HISTORY,
        translation_key=SUFFIX_HISTORY,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:history",
        value_fn=lambda snap: len(snap.history),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create the entities for every 户号 stored in the config entry."""
    coordinator: ZSWaterCoordinator = hass.data[DOMAIN][entry.entry_id]
    accounts: dict[str, dict[str, Any]] = entry.data.get(CONF_WATER_ACCOUNTS, {}) or {}

    entities = [
        ZSWaterSensor(coordinator, entry, meter_number, definition)
        for meter_number in accounts
        for definition in _SENSOR_DEFINITIONS
    ]
    async_add_entities(entities)


class ZSWaterSensor(CoordinatorEntity[ZSWaterCoordinator], SensorEntity):
    """One measurement for one 户号."""

    entity_description: ZSWaterSensorDefinition
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: ZSWaterCoordinator,
        entry: ConfigEntry,
        meter_number: str,
        definition: ZSWaterSensorDefinition,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = definition
        self._entry = entry
        self._meter_number = meter_number
        self._attr_unique_id = (
            f"{DOMAIN}.{entry.entry_id}.{meter_number}.{definition.key}"
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}:{meter_number}")},
            via_device=(DOMAIN, entry.entry_id),
            name=self._meter_label,
            manufacturer="中山公用水务",
            model="水表户号",
            configuration_url="https://smartbi.zsws.com.cn/",
        )

    @property
    def _snapshot(self) -> MeterSnapshot | None:
        return (self.coordinator.data or {}).get(self._meter_number)

    @property
    def _meter_label(self) -> str:
        stored = (self._entry.data.get(CONF_WATER_ACCOUNTS, {}) or {}).get(
            self._meter_number, {}
        )
        name = stored.get("name")
        address = stored.get("address")
        if name and address:
            return f"{name} ({address})"
        return str(name or address or self._meter_number)

    @property
    def available(self) -> bool:
        """Only report state when we actually have a value for this 户号."""
        if not super().available:
            return False
        snapshot = self._snapshot
        if snapshot is None:
            return False
        return self.entity_description.value_fn(snapshot) is not None

    @property
    def native_value(self) -> Any:
        snapshot = self._snapshot
        if snapshot is None:
            return None
        return self.entity_description.value_fn(snapshot)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose account context, and the full billing history where useful."""
        snapshot = self._snapshot
        if snapshot is None:
            return {}
        account = snapshot.account
        attributes: dict[str, Any] = {
            ATTR_KEY_METER_NUMBER: account.meter_number,
            ATTR_KEY_METER_NAME: account.name,
            ATTR_KEY_ADDRESS: account.address,
            ATTR_KEY_ACCOUNT_STATUS: account.status,
        }
        if self.entity_description.key == SUFFIX_HISTORY:
            attributes[ATTR_KEY_HISTORY] = snapshot.history
        if self.entity_description.key == SUFFIX_CURRENT_READING:
            detail = snapshot.detail
            if detail is not None:
                attributes[ATTR_KEY_IS_TIERED] = detail.is_tiered
                attributes[ATTR_KEY_TIER1_REMAINING] = detail.tier1_remaining
                attributes[ATTR_KEY_TIER2_REMAINING] = detail.tier2_remaining
        return attributes
