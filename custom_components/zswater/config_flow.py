"""Config flow for the Zhongshan Water integration.

Login
-----
One route, mirroring the portal's own login card field for field::

    手机号  [获取手机验证码]      →  GET /iwater/v1/usercenter/nt/sendAuthCode/v4.json
    手机验证码  (form field "code")
    密码                         →  POST /iwater/nt/wt/login.json

An earlier revision of this file asked for a 图形验证码 instead. That was wrong:
the portal's login form does not render one. Its ``captchaUrl``/``keyDate``
state is dead code — the render evaluates ``this.state.captchaUrl;`` and never
places an image — while the fields it really draws are ``meterPhone``, the
``code`` input whose placeholder is 请输入手机验证码, and ``password``. The SMS
button posts ``{mobile, type: 2}``.

Two further routes exist in the portal but are deliberately not offered:

``wechat``
    微信 ``unionid`` (``/iwater/nt/wt/logining.json``). The portal reads the
    value out of its own redirect URL, so it is only ever present when the site
    is entered from the 公众号 menu; there is no way for a user to look it up.
``sso``
    广东统一身份认证 (``/iwater/sso/login.json``), exchanging the ``ticket``
    and ``sp`` a ``tyrz.gd.gov.cn`` redirect appends.
"""

from __future__ import annotations

import logging
import socket
import time
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.const import CONF_PASSWORD
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .config import (
    get_configured_history_days,
    get_configured_ip_family,
    get_configured_update_interval,
)
from .const import (
    ABORT_ALL_ADDED,
    ABORT_NO_ACCOUNT,
    CONF_ACCOUNT_NUMBER,
    CONF_HISTORY_DAYS,
    CONF_IP_FAMILY,
    CONF_LOGIN_TYPE,
    CONF_METER_NAME,
    CONF_METER_NUMBER,
    CONF_METER_PHONE,
    CONF_SMS_CODE,
    CONF_UPDATE_INTERVAL,
    CONF_UPDATED_AT,
    CONF_WATER_ACCOUNTS,
    DEFAULT_HISTORY_DAYS,
    DEFAULT_IP_FAMILY,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    ERROR_CANNOT_CONNECT,
    ERROR_INVALID_AUTH,
    ERROR_NO_SMS_CODE,
    ERROR_SMS_CODE_INVALID,
    ERROR_UNKNOWN,
    IP_FAMILY_OPTIONS,
    MIN_UPDATE_INTERVAL,
    PORTAL_URL,
    SETTING_UPDATE_TIMEOUT,
    STEP_ADD_ACCOUNT,
    STEP_ADD_ACCOUNT_VERIFY,
    STEP_CREDENTIALS,
    STEP_INIT,
    STEP_NO_ACCOUNT,
    STEP_SETTINGS,
    STEP_SMS_CODE,
    STEP_USER,
)
from .coordinator import ZSWaterCoordinator
from .zswater_client import (
    LoginType,
    SMS_TYPE_VERIFY,
    WaterAccount,
    ZSWaterApiError,
    ZSWaterAuthError,
    ZSWaterClient,
    ZSWaterError,
    ZSWaterTransportError,
)

_LOGGER = logging.getLogger(__name__)

_IP_FAMILY_TO_SOCKET: dict[str, int] = {
    "ipv4": socket.AF_INET,
    "ipv6": socket.AF_INET6,
}


def _account_label(account: WaterAccount) -> str:
    """Human-readable 户号 label for a select option."""
    parts = [account.meter_number]
    if account.name:
        parts.append(account.name)
    if account.address:
        parts.append(account.address)
    return " · ".join(parts)


class ZSWaterConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the add-integration wizard."""

    VERSION = 1

    def __init__(self) -> None:
        self._ip_family: str = DEFAULT_IP_FAMILY
        self._login_type: str | None = None
        self._client: ZSWaterClient | None = None
        self._mobile: str | None = None
        self._reauth_entry: ConfigEntry | None = None
        self._is_reconfigure: bool = False
        self._pending_password: str | None = None

    # ------------------------------------------------------------ helpers

    def _new_client(self) -> ZSWaterClient:
        """Build a client bound to the address family chosen in step one."""
        session = async_get_clientsession(
            self.hass, family=_IP_FAMILY_TO_SOCKET.get(self._ip_family, socket.AF_UNSPEC)
        )
        return ZSWaterClient(session, timeout=SETTING_UPDATE_TIMEOUT)

    async def _async_finish_login(self) -> FlowResult:
        """Continue to 户号 selection, or write the refreshed token on reauth."""
        assert self._client is not None
        if self._reauth_entry is not None:
            entry = self._reauth_entry
            self.hass.config_entries.async_update_entry(
                entry,
                data={
                    **entry.data,
                    CONF_AUTH_TOKEN: self._client.token,
                    CONF_LOGIN_TYPE: self._login_type,
                    CONF_UPDATED_AT: str(int(time.time() * 1000)),
                },
            )
            return self.async_abort(
                reason="reconfigure_successful"
                if self._is_reconfigure
                else "reauth_successful"
            )
        return await self.async_step_init()

    # --------------------------------------------------------------- steps

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 1 — pick the network address family before logging in."""
        if user_input is not None:
            self._ip_family = user_input[CONF_IP_FAMILY]
            return await self.async_step_credentials()
        return self.async_show_form(
            step_id=STEP_USER,
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_IP_FAMILY, default=DEFAULT_IP_FAMILY
                    ): vol.In(IP_FAMILY_OPTIONS)
                }
            ),
            description_placeholders={"portal_url": PORTAL_URL},
        )

    async def async_step_credentials(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 2 — 手机号 + 密码; submitting texts a 短信验证码 and moves on."""
        errors: dict[str, str] = {}
        if user_input is not None:
            client = self._new_client()
            mobile = user_input[CONF_ACCOUNT_NUMBER]
            try:
                # The portal has no separate "check the password" call, so the
                # code is requested against the phone number and the password is
                # only verified when the code is submitted.
                await client.async_send_sms_code(mobile, SMS_TYPE_VERIFY)
            except ZSWaterTransportError:
                errors["base"] = ERROR_CANNOT_CONNECT
            except ZSWaterError as err:
                errors["base"] = ERROR_NO_SMS_CODE
                _LOGGER.warning("短信验证码发送失败: %s", err)
            else:
                self._client = client
                self._mobile = mobile
                # Held only for the lifetime of the flow: the portal verifies
                # the password when the code is submitted, not before.
                self._pending_password = user_input[CONF_PASSWORD]
                return await self.async_step_sms_code()

        return self.async_show_form(
            step_id=STEP_CREDENTIALS,
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ACCOUNT_NUMBER, default=self._mobile or ""): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
            description_placeholders={"portal_url": PORTAL_URL},
        )

    async def async_step_sms_code(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 3 — 短信验证码, submitted together with the password."""
        errors: dict[str, str] = {}
        assert self._client is not None
        assert self._mobile is not None

        if user_input is not None:
            try:
                await self._client.async_login(
                    self._mobile,
                    self._pending_password or "",
                    user_input[CONF_SMS_CODE],
                    # The portal's form keeps a millisecond timestamp beside its
                    # (unrendered) captcha state and posts it with the login; a
                    # fresh one is just as acceptable to the endpoint.
                    int(time.time() * 1000),
                )
            except (ZSWaterAuthError, ZSWaterApiError) as err:
                errors["base"] = ERROR_INVALID_AUTH
                errors[CONF_SMS_CODE] = ERROR_SMS_CODE_INVALID
                _LOGGER.debug("登录被门户拒绝: %s", err)
            except ZSWaterTransportError:
                errors["base"] = ERROR_CANNOT_CONNECT
            except ZSWaterError as err:
                errors["base"] = ERROR_UNKNOWN
                _LOGGER.exception("登录异常: %s", err)
            else:
                self._login_type = LoginType.PASSWORD
                return await self._async_finish_login()

        return self.async_show_form(
            step_id=STEP_SMS_CODE,
            data_schema=vol.Schema({vol.Required(CONF_SMS_CODE): str}),
            errors=errors,
            description_placeholders={"mobile": self._mobile},
        )

    async def async_step_no_account(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 4 — the portal has no 户号 bound to this account yet.

        ``queryUserMeterList`` only ever returns 户号 bound *inside the portal*;
        its own client says 「您还没有绑定户号，请去绑定户号」 for the same case.
        A 户号 shown by the mobile app or a 小程序 belongs to a different
        front-end and does not appear here until it is bound on the web too.

        Submitting this form simply re-runs the lookup, so the user can bind it
        in a browser and continue without starting over.
        """
        if user_input is not None:
            return await self.async_step_init()
        return self.async_show_form(
            step_id=STEP_NO_ACCOUNT,
            data_schema=vol.Schema({}),
            description_placeholders={"portal_url": PORTAL_URL},
        )

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 5 — choose which 户号 to monitor."""
        assert self._client is not None
        try:
            accounts = await self._client.async_get_accounts()
        except ZSWaterAuthError:
            return self.async_abort(reason=ERROR_INVALID_AUTH)
        except ZSWaterError:
            return self.async_abort(reason=ERROR_CANNOT_CONNECT)

        if not accounts:
            # Not an error: the portal simply has nothing bound yet. Explain how
            # to fix that and let the user re-check without restarting the flow.
            return await self.async_step_no_account()

        by_number = {account.meter_number: account for account in accounts}

        if user_input is not None:
            selected = user_input[CONF_WATER_ACCOUNTS]
            if isinstance(selected, str):
                selected = [selected]
            chosen = {
                number: by_number[number].as_stored()
                for number in selected
                if number in by_number
            }
            if not chosen:
                return self.async_abort(reason=ABORT_NO_ACCOUNT)

            mobile = self._mobile or "unknown"
            await self.async_set_unique_id(mobile, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=f"中山公用水务 {mobile}",
                data={
                    CONF_ACCOUNT_NUMBER: mobile,
                    CONF_LOGIN_TYPE: self._login_type or LoginType.PASSWORD,
                    CONF_AUTH_TOKEN: self._client.token,
                    CONF_WATER_ACCOUNTS: chosen,
                    CONF_UPDATED_AT: str(int(time.time() * 1000)),
                },
                options={
                    CONF_IP_FAMILY: self._ip_family,
                    CONF_UPDATE_INTERVAL: DEFAULT_UPDATE_INTERVAL,
                    CONF_HISTORY_DAYS: DEFAULT_HISTORY_DAYS,
                },
            )

        return self.async_show_form(
            step_id=STEP_INIT,
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_WATER_ACCOUNTS, default=list(by_number)
                    ): cv.multi_select(
                        {number: _account_label(a) for number, a in by_number.items()}
                    )
                }
            ),
            description_placeholders={"count": str(len(accounts))},
        )

    # -------------------------------------------------------------- shared

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> "ZSWaterOptionsFlow":
        """Return the options flow handler."""
        return ZSWaterOptionsFlow()

    # -------------------------------------------------------------- reauth

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> FlowResult:
        """Re-authenticate an entry whose token expired."""
        entry = self._get_reauth_entry()
        self._reauth_entry = entry
        self._ip_family = get_configured_ip_family(entry)
        self._mobile = entry.data.get(CONF_ACCOUNT_NUMBER)
        return await self.async_step_credentials()

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Refresh credentials without deleting the entry."""
        entry = self._get_reconfigure_entry()
        self._reauth_entry = entry
        self._is_reconfigure = True
        self._ip_family = get_configured_ip_family(entry)
        self._mobile = entry.data.get(CONF_ACCOUNT_NUMBER)
        return await self.async_step_credentials()


class ZSWaterOptionsFlow(OptionsFlow):
    """Add 户号, bind a new one, or change the polling settings.

    Deliberately defines no ``__init__``: Home Assistant constructs options
    flows itself, and the base-class signature changed between releases. The
    transient ``_pending`` attribute is simply assigned when first needed.
    """

    # ------------------------------------------------------------ helpers

    @property
    def _coordinator(self) -> ZSWaterCoordinator:
        return self.hass.data[DOMAIN][self.config_entry.entry_id]

    @property
    def _monitored(self) -> dict[str, Any]:
        return dict(self.config_entry.data.get(CONF_WATER_ACCOUNTS, {}) or {})

    def _async_save_options(self) -> FlowResult:
        """Persist options; the entry's update listener reloads the entry."""
        return self.async_create_entry(
            title="",
            data={
                CONF_IP_FAMILY: self.config_entry.options.get(
                    CONF_IP_FAMILY, DEFAULT_IP_FAMILY
                ),
                CONF_UPDATE_INTERVAL: self.config_entry.options.get(
                    CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL
                ),
                CONF_HISTORY_DAYS: self.config_entry.options.get(
                    CONF_HISTORY_DAYS, DEFAULT_HISTORY_DAYS
                ),
            },
        )

    def _async_add_accounts(self, accounts: list[WaterAccount]) -> FlowResult:
        """Merge freshly-read 户号 into the entry and reload."""
        merged = self._monitored
        for account in accounts:
            merged[account.meter_number] = account.as_stored()
        self.hass.config_entries.async_update_entry(
            self.config_entry,
            data={
                **self.config_entry.data,
                CONF_WATER_ACCOUNTS: merged,
                CONF_UPDATED_AT: str(int(time.time() * 1000)),
            },
        )
        return self._async_save_options()

    # --------------------------------------------------------------- steps

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Options menu."""
        return self.async_show_menu(
            step_id=STEP_INIT,
            menu_options=[STEP_ADD_ACCOUNT, "bind_account", STEP_SETTINGS],
        )

    async def async_step_add_account(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Monitor 户号 that are already bound on the portal."""
        monitored = self._monitored
        try:
            accounts = await self._coordinator.async_list_portal_accounts()
        except ZSWaterError as err:
            _LOGGER.warning("读取门户户号失败: %s", err)
            return self.async_abort(reason=ERROR_CANNOT_CONNECT)

        available = {
            account.meter_number: account
            for account in accounts
            if account.meter_number not in monitored
        }
        if not available:
            return self.async_abort(reason=ABORT_ALL_ADDED)

        if user_input is not None:
            selected = user_input[CONF_WATER_ACCOUNTS]
            if isinstance(selected, str):
                selected = [selected]
            return self._async_add_accounts(
                [available[number] for number in selected if number in available]
            )

        return self.async_show_form(
            step_id=STEP_ADD_ACCOUNT,
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_WATER_ACCOUNTS): cv.multi_select(
                        {
                            number: _account_label(account)
                            for number, account in available.items()
                        }
                    )
                }
            ),
            description_placeholders={"count": str(len(available))},
        )

    async def async_step_bind_account(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Bind a 户号 that is not on the portal account yet.

        The portal gates this behind a 短信验证码 sent to the phone registered
        against the meter, so the flow looks the address up first and then
        verifies the code.
        """
        errors: dict[str, str] = {}
        if user_input is not None:
            number = user_input[CONF_METER_NUMBER]
            name = user_input[CONF_METER_NAME]
            phone = user_input[CONF_METER_PHONE]
            try:
                address = await self._coordinator.client.async_search_meter(number, name)
            except ZSWaterError as err:
                errors["base"] = ERROR_UNKNOWN
                _LOGGER.debug("户号查询失败: %s", err)
            else:
                self._pending = {
                    CONF_METER_NUMBER: number,
                    CONF_METER_NAME: name,
                    CONF_METER_PHONE: phone,
                    "address": address or "",
                }
                try:
                    await self._coordinator.client.async_send_sms_code(
                        phone, SMS_TYPE_VERIFY
                    )
                except ZSWaterError as err:
                    errors["base"] = ERROR_NO_SMS_CODE
                    _LOGGER.warning("绑定户号短信验证码发送失败: %s", err)
                else:
                    return await self.async_step_add_account_verify()

        return self.async_show_form(
            step_id="bind_account",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_METER_NUMBER): str,
                    vol.Required(CONF_METER_NAME): str,
                    vol.Required(CONF_METER_PHONE): str,
                }
            ),
            errors=errors,
            description_placeholders={"portal_url": PORTAL_URL},
        )

    async def async_step_add_account_verify(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Confirm the 短信验证码 and bind the 户号."""
        errors: dict[str, str] = {}
        pending: dict[str, str] = getattr(self, "_pending", {})
        if user_input is not None:
            code = user_input[CONF_SMS_CODE]
            client = self._coordinator.client
            try:
                if not await client.async_check_phone_code(
                    code, pending.get(CONF_METER_PHONE, "")
                ):
                    errors[CONF_SMS_CODE] = ERROR_SMS_CODE_INVALID
                else:
                    bound = await self._async_find_account(
                        pending.get(CONF_METER_NUMBER, "")
                    )
                    if bound is None:
                        await client.async_bind_meter(
                            pending.get(CONF_METER_NUMBER, ""),
                            pending.get(CONF_METER_NAME, ""),
                            phone=pending.get(CONF_METER_PHONE, ""),
                            address=pending.get("address") or None,
                            verify_code=code,
                        )
                        bound = await self._async_find_account(
                            pending.get(CONF_METER_NUMBER, "")
                        )
                    if bound is None:
                        errors["base"] = ERROR_UNKNOWN
                    else:
                        return self._async_add_accounts([bound])
            except ZSWaterTransportError:
                errors["base"] = ERROR_CANNOT_CONNECT
            except ZSWaterError as err:
                errors["base"] = ERROR_UNKNOWN
                _LOGGER.debug("绑定户号失败: %s", err)

        return self.async_show_form(
            step_id=STEP_ADD_ACCOUNT_VERIFY,
            data_schema=vol.Schema({vol.Required(CONF_SMS_CODE): str}),
            errors=errors,
            description_placeholders={"mobile": pending.get(CONF_METER_PHONE, "")},
        )

    async def _async_find_account(self, meter_number: str) -> WaterAccount | None:
        """Return ``meter_number`` from the portal, or ``None``."""
        for candidate in await self._coordinator.client.async_get_accounts():
            if candidate.meter_number == meter_number:
                return candidate
        return None

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Change the refresh interval, address family and history window."""
        if user_input is not None:
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                options={
                    CONF_IP_FAMILY: user_input[CONF_IP_FAMILY],
                    CONF_UPDATE_INTERVAL: int(user_input[CONF_UPDATE_INTERVAL]),
                    CONF_HISTORY_DAYS: int(user_input[CONF_HISTORY_DAYS]),
                },
            )
            return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id=STEP_SETTINGS,
            data_schema=self._settings_schema(),
        )

    def _settings_schema(self) -> vol.Schema:
        entry = self.config_entry
        return vol.Schema(
            {
                vol.Required(
                    CONF_UPDATE_INTERVAL,
                    default=get_configured_update_interval(entry),
                ): vol.All(vol.Coerce(int), vol.Range(min=MIN_UPDATE_INTERVAL)),
                vol.Required(
                    CONF_HISTORY_DAYS,
                    default=get_configured_history_days(entry),
                ): vol.All(vol.Coerce(int), vol.Range(min=30, max=1095)),
                vol.Required(
                    CONF_IP_FAMILY, default=get_configured_ip_family(entry)
                ): vol.In(IP_FAMILY_OPTIONS),
            }
        )
