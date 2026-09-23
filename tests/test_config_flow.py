"""End-to-end config-flow tests against a real Home Assistant instance.

The other test modules check pieces in isolation; this one drives the wizard the
way the frontend does, through ``hass.config_entries.flow``. That is what
catches a step that raises while rendering or while creating the entry — Home
Assistant turns such an exception into a generic "Unknown error occurred" in the
UI, which no unit test of the step's own logic would ever surface.
"""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType

from custom_components.zswater import config_flow
from custom_components.zswater.const import (
    CONF_ACCOUNT_NUMBER,
    CONF_IP_FAMILY,
    CONF_SMS_CODE,
    CONF_WATER_ACCOUNTS,
    DOMAIN,
)
from custom_components.zswater.zswater_client import WaterAccount

MOBILE = "18689399832"


class FakeClient:
    """Stands in for :class:`ZSWaterClient`, so no request leaves the machine."""

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        self.token = ""

    async def async_send_sms_code(self, _mobile: str, _code_type: int) -> str:
        return "验证码已发送"

    async def async_login(
        self, _mobile: str, _password: str, _sms_code: Any, _timestamp: Any = None
    ) -> dict[str, Any]:
        self.token = "TOKEN"
        return {"userInfo": {"token": "TOKEN"}}

    async def async_get_accounts(self) -> list[WaterAccount]:
        return [
            WaterAccount(
                meter_number="100239734",
                name="*海亮",
                address="悦盈新成花园19幢303",
                area=None,
            )
        ]


class EmptyClient(FakeClient):
    """A portal account with nothing bound to it."""

    async def async_get_accounts(self) -> list[WaterAccount]:
        return []


def _patch_client(monkeypatch: pytest.MonkeyPatch, cls: type[FakeClient]) -> None:
    monkeypatch.setattr(config_flow, "ZSWaterClient", cls)
    # The fake never opens a session, and building a real one goes through
    # aiohttp's aiodns resolver, which refuses to run on the Proactor loop that
    # Windows defaults to ("aiodns needs a SelectorEventLoop on Windows"). The
    # session object itself is never touched, so hand back a placeholder.
    monkeypatch.setattr(config_flow, "async_get_clientsession", lambda *_a, **_k: None)


@pytest.fixture(name="client")
def client_fixture(monkeypatch: pytest.MonkeyPatch) -> type[FakeClient]:
    _patch_client(monkeypatch, FakeClient)
    return FakeClient


async def _drive_to_accounts(hass, client) -> dict[str, Any]:
    """Walk 网络设置 → 登录 → 短信验证码 and return the 户号 step result."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM, result
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_IP_FAMILY: "auto"}
    )
    assert result["type"] is FlowResultType.FORM, result
    assert result["step_id"] == "credentials"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ACCOUNT_NUMBER: MOBILE, "password": "secret"}
    )
    assert result["type"] is FlowResultType.FORM, result
    assert result["step_id"] == "sms_code"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_SMS_CODE: "123456"}
    )
    assert result["type"] is FlowResultType.FORM, result
    return result


@pytest.mark.asyncio
async def test_full_flow_creates_the_entry(hass, client) -> None:
    """The wizard must reach CREATE_ENTRY without raising."""
    result = await _drive_to_accounts(hass, client)
    assert result["step_id"] == "init"
    assert result["description_placeholders"]["count"] == "1"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_WATER_ACCOUNTS: ["100239734"]}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY, result
    assert result["data"][CONF_ACCOUNT_NUMBER] == MOBILE
    assert list(result["data"][CONF_WATER_ACCOUNTS]) == ["100239734"]
    assert result["data"][CONF_WATER_ACCOUNTS]["100239734"]["address"] == (
        "悦盈新成花园19幢303"
    )


@pytest.mark.asyncio
async def test_entry_data_survives_a_round_trip(hass, client) -> None:
    """Config entry data is persisted as JSON; it must serialise cleanly."""
    import json

    result = await _drive_to_accounts(hass, client)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_WATER_ACCOUNTS: ["100239734"]}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY, result

    json.dumps(result["data"])
    json.dumps(result["options"])


@pytest.mark.asyncio
async def test_empty_portal_account_offers_the_binding_help(
    hass, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No bound 户号 is a guided step, not a dead end."""
    _patch_client(monkeypatch, EmptyClient)

    result = await _drive_to_accounts(hass, EmptyClient)

    assert result["type"] is FlowResultType.FORM, result
    assert result["step_id"] == "no_account"
    assert result["description_placeholders"]["portal_url"].startswith("https://")
