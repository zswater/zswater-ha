"""Integration-level tests that exercise the real Home Assistant modules.

Importing every module of the custom component is itself the check here: it
catches wrong Home Assistant imports, renamed constants and broken entity
declarations without needing a running Home Assistant instance.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

COMPONENT_DIR = Path(__file__).resolve().parents[1] / "custom_components"
PACKAGE = "zswater"

# Home Assistant is only present in the test environment.
pytest.importorskip("homeassistant")

sys.path.insert(0, str(COMPONENT_DIR))

config_flow = importlib.import_module(f"{PACKAGE}.config_flow")
const = importlib.import_module(f"{PACKAGE}.const")


def test_every_module_imports() -> None:
    for module in (
        PACKAGE,
        f"{PACKAGE}.captcha",
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


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("oABC-123_def", "oABC-123_def"),
        ("  oABC-123_def  ", "oABC-123_def"),
        (
            "https://smartbi.zsws.com.cn/?unionid=oABC-123_def#/wechatLogin",
            "oABC-123_def",
        ),
        (
            "https://smartbi.zsws.com.cn/?unionid=oABC%2D123#/wechatLogin",
            "oABC-123",
        ),
        ("UNIONID=oXYZ#/home", "oXYZ"),
    ],
)
def test_extract_unionid_accepts_bare_values_and_urls(raw: str, expected: str) -> None:
    assert config_flow._extract_unionid(raw) == expected


def test_login_menu_options_all_map_to_a_step() -> None:
    for option in const.LOGIN_TYPE_OPTIONS:
        assert str(option) in config_flow.LOGIN_MENU_TO_STEP

    assert config_flow.LOGIN_MENU_TO_STEP[const.LoginType.PASSWORD] == (
        const.STEP_PASSWORD_LOGIN
    )
    assert config_flow.LOGIN_MENU_TO_STEP[const.LoginType.WECHAT] == (
        const.STEP_WECHAT_LOGIN
    )
    assert config_flow.LOGIN_MENU_TO_STEP[const.LoginType.SMS] == (
        const.STEP_SMS_REGISTER
    )


def test_login_menu_steps_exist_on_the_flow() -> None:
    for step in config_flow.LOGIN_MENU_TO_STEP.values():
        assert hasattr(config_flow.ZSWaterConfigFlow, f"async_step_{step}")


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
