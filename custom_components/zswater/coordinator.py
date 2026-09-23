"""Data update coordinator for the Zhongshan Water integration."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .config import get_configured_history_days, get_configured_update_interval
from .const import DOMAIN
from .zswater_client import (
    MeterSnapshot,
    WaterAccount,
    ZSWaterAuthError,
    ZSWaterClient,
    ZSWaterError,
    ZSWaterTransportError,
)

_LOGGER = logging.getLogger(__name__)


class ZSWaterCoordinator(DataUpdateCoordinator[dict[str, MeterSnapshot]]):
    """Fetch every monitored 户号 on a fixed interval.

    One coordinator per config entry, mirroring the "one entry per portal
    account" model: the portal session is account-scoped, so two phone numbers
    must not share a coordinator.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: ZSWaterClient,
    ) -> None:
        self.entry = entry
        self.client = client
        self._history_days = get_configured_history_days(entry)
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}:{entry.data.get('account_number', entry.entry_id)}",
            update_interval=timedelta(
                seconds=get_configured_update_interval(entry)
            ),
        )

    # ------------------------------------------------------------- fetching

    async def _async_update_data(self) -> dict[str, MeterSnapshot]:
        """Fetch all 户号, their money fields, readings and billing history."""
        try:
            accounts = await self.client.async_get_accounts()
        except ZSWaterAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except ZSWaterTransportError as err:
            raise UpdateFailed(f"无法连接中山公用水务: {err}") from err
        except ZSWaterError as err:
            raise UpdateFailed(str(err)) from err

        if not accounts:
            raise UpdateFailed("该账号下没有已绑定的户号")

        monitored = set(self.entry.data.get("accounts", {}) or {})
        snapshots: dict[str, MeterSnapshot] = {}

        for account in accounts:
            detail = None
            readings = []
            if account.meter_number in monitored:
                detail, readings = await self._async_fetch_detail(account)
            snapshots[account.meter_number] = MeterSnapshot(
                account=account, detail=detail, readings=readings
            )

        unmonitored = set(snapshots) - monitored
        if unmonitored:
            _LOGGER.info(
                "门户中还有未接入的户号 %s，可在集成选项中添加",
                ", ".join(sorted(unmonitored)),
            )
        return snapshots

    async def _async_fetch_detail(
        self, account: WaterAccount
    ) -> tuple[Any, list[Any]]:
        """Fetch one 户号's meter detail and billing history.

        A failure here degrades that 户号's readings to ``None`` rather than
        failing the whole refresh, because the account list already succeeded
        and still carries the money fields the user cares about most.
        """
        detail = None
        readings: list[Any] = []
        try:
            detail = await self.client.async_get_meter_detail(
                account.meter_number, account.name
            )
        except ZSWaterAuthError:
            raise
        except ZSWaterError as err:
            _LOGGER.warning(
                "户号 %s 抄表信息获取失败: %s", account.meter_number, err
            )
        try:
            readings = await self.client.async_get_readings(
                account.meter_number, days=self._history_days
            )
        except ZSWaterAuthError:
            raise
        except ZSWaterError as err:
            _LOGGER.warning(
                "户号 %s 用水记录获取失败: %s", account.meter_number, err
            )
        return detail, readings

    # -------------------------------------------------------------- helpers

    async def async_list_portal_accounts(self) -> list[WaterAccount]:
        """Return every 户号 bound to the portal account right now."""
        return await self.client.async_get_accounts()
