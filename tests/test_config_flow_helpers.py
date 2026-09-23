"""Integration-level tests that exercise the real Home Assistant modules.

Importing every module of the custom component is itself the check here: it
catches wrong Home Assistant imports, renamed constants and broken entity
declarations without needing a running Home Assistant instance.

Everything is imported as ``custom_components.zswater.*`` — the same module
objects Home Assistant's loader uses. Importing the package a second way (by
putting ``custom_components/`` on ``sys.path``) produces a duplicate module
identity that quietly breaks the config-flow tests.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

# Home Assistant is only present in the test environment.
pytest.importorskip("homeassistant")

from custom_components.zswater import config_flow, const  # noqa: E402

PACKAGE = "custom_components.zswater"
PACKAGE_DIR = Path(config_flow.__file__).resolve().parent


def test_every_module_imports() -> None:
    for module in (
        PACKAGE,
        f"{PACKAGE}.config",
        f"{PACKAGE}.config_flow",
        f"{PACKAGE}.const",
        f"{PACKAGE}.coordinator",
        f"{PACKAGE}.sensor",
        f"{PACKAGE}.binary_sensor",
        f"{PACKAGE}.zswater_client",
        f"{PACKAGE}.zswater_client.models",
    ):
        assert importlib.import_module(module) is not None


def test_sensor_table_covers_the_three_required_readings() -> None:
    sensor = importlib.import_module(f"{PACKAGE}.sensor")
    keys = {definition.key for definition in sensor._SENSOR_DEFINITIONS}

    assert const.SUFFIX_ARREARS in keys
    assert const.SUFFIX_LAST_READING in keys
    assert const.SUFFIX_CURRENT_READING in keys
    assert const.SUFFIX_USAGE in keys


def test_sensor_keys_and_translation_keys_match() -> None:
    sensor = importlib.import_module(f"{PACKAGE}.sensor")

    for definition in sensor._SENSOR_DEFINITIONS:
        assert definition.key == definition.translation_key, definition.key
        assert definition.value_fn is not None


def test_sensor_unique_ids_are_distinct() -> None:
    sensor = importlib.import_module(f"{PACKAGE}.sensor")
    keys = [definition.key for definition in sensor._SENSOR_DEFINITIONS]

    assert len(keys) == len(set(keys))


def test_login_walks_the_portals_own_form() -> None:
    """The login is 手机号 + 密码, then the 短信验证码 the portal texts.

    No menu: the previous revision offered three routes, of which the captcha
    one did not exist and the other two needed values a user cannot obtain.
    """
    assert not hasattr(config_flow.ZSWaterConfigFlow, "async_step_login_type")
    for step in (const.STEP_USER, const.STEP_CREDENTIALS, const.STEP_SMS_CODE):
        assert hasattr(config_flow.ZSWaterConfigFlow, f"async_step_{step}"), step


def test_an_unbound_portal_account_is_guided_not_aborted() -> None:
    """An empty 户号 list must lead somewhere, not just stop.

    The portal's list endpoint returns only 户号 bound *inside the portal*, so a
    correctly configured account can legitimately come back empty. Aborting
    there told the user nothing actionable; the flow now explains how to bind
    one and re-checks on submit.
    """
    source = (PACKAGE_DIR / "config_flow.py").read_text(encoding="utf-8")
    assert "return await self.async_step_no_account()" in source
    assert hasattr(config_flow.ZSWaterConfigFlow, "async_step_no_account")


@pytest.mark.parametrize(
    "removed",
    [
        "async_get_captcha",
        "_async_prepare_captcha",
        "CONF_CAPTCHA_CODE",
        "STEP_PASSWORD_LOGIN",
        "STEP_WECHAT_LOGIN",
        "STEP_SMS_REGISTER",
        "LOGIN_MENU_OPTIONS",
        "_extract_unionid",
        "SMS_TYPE_BIND_METER",
    ],
)
def test_removed_login_machinery_stays_removed(removed: str) -> None:
    """Guards the reversal of the wrong login design.

    The portal's login form is 手机号 + 短信验证码 + 密码; an earlier revision
    invented a 图形验证码 step and two unusable routes instead.
    """
    for filename in ("const.py", "config_flow.py"):
        source = (PACKAGE_DIR / filename).read_text(encoding="utf-8")
        assert removed not in source, f"{removed} came back in {filename}"


def test_account_label_includes_every_known_field() -> None:
    models = importlib.import_module(f"{PACKAGE}.zswater_client.models")
    account = models.WaterAccount.from_api(
        {"meterNumber": "123", "meterName": "张三", "meterAddress": "某路1号"}
    )

    label = config_flow._account_label(account)
    assert "123" in label
    assert "张三" in label
    assert "某路1号" in label


def test_account_label_tolerates_missing_name_and_address() -> None:
    models = importlib.import_module(f"{PACKAGE}.zswater_client.models")
    account = models.WaterAccount.from_api({"meterNumber": "123"})

    assert config_flow._account_label(account) == "123"


def test_ip_family_options_are_all_resolvable() -> None:
    for option in const.IP_FAMILY_OPTIONS:
        assert option in config_flow._IP_FAMILY_TO_SOCKET or option == "auto"


def test_streams_did_not_leak_into_the_client_package() -> None:
    """The client must stay usable without Home Assistant."""
    client = importlib.import_module(f"{PACKAGE}.zswater_client")
    source = Path(client.__file__).read_text(encoding="utf-8")

    assert "homeassistant" not in source
    assert "voluptuous" not in source
