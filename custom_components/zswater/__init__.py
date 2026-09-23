"""The Zhongshan Water (中山公用水务) integration."""

from __future__ import annotations

import copy
import logging
import time
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry
from homeassistant.helpers.device_registry import DeviceEntry

from .captcha import async_register_captcha_view
from .config import async_get_zswater_clientsession
from .const import (
    CONF_AUTH_TOKEN,
    CONF_UPDATED_AT,
    CONF_WATER_ACCOUNTS,
    DOMAIN,
    SETTING_UPDATE_TIMEOUT,
)
from .coordinator import ZSWaterCoordinator
from .zswater_client import ZSWaterClient

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR]

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Register the captcha endpoint used by the password login flow."""
    hass.data.setdefault(DOMAIN, {})
    async_register_captcha_view(hass)
    return True


def _create_entry_update_listener(
    initial_data: Mapping[str, Any],
    initial_options: Mapping[str, Any],
) -> Callable[[HomeAssistant, ConfigEntry], Awaitable[None]]:
    """Reload the entry when either its data or its options change."""
    previous_data = copy.deepcopy(dict(initial_data))
    previous_options = copy.deepcopy(dict(initial_options))

    async def _async_reload_on_update(
        hass: HomeAssistant, updated_entry: ConfigEntry
    ) -> None:
        nonlocal previous_data, previous_options
        if (
            updated_entry.data == previous_data
            and updated_entry.options == previous_options
        ):
            return
        previous_data = copy.deepcopy(dict(updated_entry.data))
        previous_options = copy.deepcopy(dict(updated_entry.options))
        await hass.config_entries.async_reload(updated_entry.entry_id)

    return _async_reload_on_update


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up one portal account from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    session = async_get_zswater_clientsession(hass, entry)
    client = ZSWaterClient(
        session,
        token=entry.data[CONF_AUTH_TOKEN],
        timeout=SETTING_UPDATE_TIMEOUT,
    )

    coordinator = ZSWaterCoordinator(hass, entry, client)
    # Raises ConfigEntryAuthFailed when the token is gone (which triggers the
    # reauth flow) and ConfigEntryNotReady when the portal is unreachable.
    await coordinator.async_config_entry_first_refresh()
    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Hub device: every 户号 device points at it through ``via_device``, so it
    # has to exist or Home Assistant drops the relationship.
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name=f"中山公用水务 {entry.data.get('account_number', '')}".strip(),
        manufacturer="中山公用水务",
        model="网上营业厅账号",
        configuration_url="https://smartbi.zsws.com.cn/",
    )

    # Older setups stored the password; the token is all we need now.
    if CONF_PASSWORD in entry.data:
        new_data = copy.deepcopy(dict(entry.data))
        new_data.pop(CONF_PASSWORD, None)
        hass.config_entries.async_update_entry(entry, data=new_data)

    entry.async_on_unload(
        entry.add_update_listener(
            _create_entry_update_listener(entry.data, entry.options)
        )
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def async_remove_config_entry_device(
    hass: HomeAssistant, config_entry: ConfigEntry, device_entry: DeviceEntry
) -> bool:
    """Drop one 户号 from the entry when its device is deleted in the UI."""
    if not device_entry.identifiers:
        return False
    identifier = next(
        (value for domain, value in device_entry.identifiers if domain == DOMAIN), None
    )
    if identifier is None:
        return False

    prefix = f"{config_entry.entry_id}:"
    if not identifier.startswith(prefix):
        # The hub device itself; removing it means removing the entry.
        return False
    meter_number = identifier.removeprefix(prefix)

    registry = entity_registry.async_get(hass)
    for entity in entity_registry.async_entries_for_config_entry(
        registry, config_entry.entry_id
    ):
        if entity.unique_id.startswith(f"{DOMAIN}.{config_entry.entry_id}.{meter_number}."):
            registry.async_remove(entity.entity_id)

    new_data = copy.deepcopy(dict(config_entry.data))
    accounts: dict[str, Any] = new_data.get(CONF_WATER_ACCOUNTS, {}) or {}
    if accounts.pop(meter_number, None) is None:
        _LOGGER.debug("户号 %s 不在配置中，跳过更新", meter_number)
        return True
    new_data[CONF_WATER_ACCOUNTS] = accounts
    new_data[CONF_UPDATED_AT] = str(int(time.time() * 1000))
    hass.config_entries.async_update_entry(config_entry, data=new_data)
    _LOGGER.info("已从集成中移除户号 %s", meter_number)
    return True


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Nothing to tear down on the portal side; the token simply expires."""
    _LOGGER.info("Removing Zhongshan Water entry for %s", entry.data.get("account_number"))
