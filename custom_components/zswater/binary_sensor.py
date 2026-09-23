"""Binary sensors for the Zhongshan Water integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_KEY_ACCOUNT_STATUS,
    ATTR_KEY_ADDRESS,
    ATTR_KEY_METER_NAME,
    ATTR_KEY_METER_NUMBER,
    CONF_WATER_ACCOUNTS,
    DOMAIN,
    SUFFIX_HAS_ARREARS,
)
from .coordinator import ZSWaterCoordinator
from .zswater_client import MeterSnapshot


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create one 欠费 binary sensor per monitored 户号."""
    coordinator: ZSWaterCoordinator = hass.data[DOMAIN][entry.entry_id]
    accounts: dict[str, dict[str, Any]] = entry.data.get(CONF_WATER_ACCOUNTS, {}) or {}
    async_add_entities(
        ZSWaterArrearsBinarySensor(coordinator, entry, meter_number)
        for meter_number in accounts
    )


class ZSWaterArrearsBinarySensor(
    CoordinatorEntity[ZSWaterCoordinator], BinarySensorEntity
):
    """``on`` while the 户号 owes money."""

    _attr_has_entity_name = True
    _attr_translation_key = SUFFIX_HAS_ARREARS
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:water-alert"

    def __init__(
        self,
        coordinator: ZSWaterCoordinator,
        entry: ConfigEntry,
        meter_number: str,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._meter_number = meter_number
        self._attr_unique_id = f"{DOMAIN}.{entry.entry_id}.{meter_number}.{SUFFIX_HAS_ARREARS}"
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
        if not super().available:
            return False
        snapshot = self._snapshot
        return snapshot is not None and snapshot.has_arrears is not None

    @property
    def is_on(self) -> bool | None:
        snapshot = self._snapshot
        return snapshot.has_arrears if snapshot is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        snapshot = self._snapshot
        if snapshot is None:
            return {}
        account = snapshot.account
        return {
            ATTR_KEY_METER_NUMBER: account.meter_number,
            ATTR_KEY_METER_NAME: account.name,
            ATTR_KEY_ADDRESS: account.address,
            ATTR_KEY_ACCOUNT_STATUS: account.status,
        }
