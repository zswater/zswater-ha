"""Standalone aiohttp client for the Zhongshan Water (中山公用水务) portal.

The module deliberately imports nothing from Home Assistant so it can be used
on its own; see ``zswater_client_demo.py`` for a runnable example.

Protocol notes
--------------
Every call goes to ``https://smartbi.zsws.com.cn`` and carries its arguments as
a single JSON document:

* ``POST`` — form body ``requestPara=<json>``, with ``+`` and ``&`` escaped but
  the rest of the JSON left raw (this is what the bundled web client does).
* ``GET``  — the same JSON as a ``requestPara`` query parameter.

The portal answers with
``{"status": 0, "errcode": 0, "errmsg": "", "message": "", "data": ...}``.
``status == 0`` means success, ``status == 11`` means the token is gone (the web
client then bounces the user to the login page), and any other non-zero status
is a business error whose ``message`` is meant for the end user. A handful of
endpoints answer with HTTP 500 instead of an envelope when a required field is
missing, so HTTP failures are surfaced as :class:`ZSWaterApiError` too.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import date, timedelta
from typing import Any, Mapping, Sequence

import aiohttp

from .const import (
    APP_VERSION,
    BASE_URL,
    COMMON_PARAMS,
    CONTENT_TYPE,
    DEFAULT_TIMEOUT,
    PATH_BILL_PAY_INFO,
    PATH_CHECK_PHONE_CODE,
    PATH_HANG_RECORD,
    PATH_LOGIN,
    PATH_METER_ADD,
    PATH_METER_INFO,
    PATH_METER_LIST,
    PATH_METER_SEARCH,
    PATH_PAY_HISTORY,
    PATH_REGISTER,
    PATH_SEND_AUTH_CODE,
    PATH_WECHAT_LOGIN,
    REQUEST_PARA_FIELD,
    REGISTER_COMMAND_WECHAT,
    SMS_TYPE_REGISTER,
    SMS_TYPE_VERIFY,
    STATUS_NOT_LOGGED_IN,
    STATUS_OK,
    LoginType,
)
from .exceptions import (
    ZSWaterApiError,
    ZSWaterAuthError,
    ZSWaterError,
    ZSWaterTransportError,
)
from .models import (
    MeterDetail,
    MeterReading,
    MeterSnapshot,
    WaterAccount,
    parse_meter_list,
    parse_readings,
)

_LOGGER = logging.getLogger(__name__)

__all__ = [
    "LoginType",
    "MeterDetail",
    "MeterReading",
    "MeterSnapshot",
    "WaterAccount",
    "ZSWaterApiError",
    "ZSWaterAuthError",
    "ZSWaterClient",
    "ZSWaterError",
    "ZSWaterTransportError",
    "md5_hex",
]

#: How far back the client looks for billing periods by default. Water bills
#: are produced roughly monthly, so three months always covers "this period"
#: and the one before it even when a reading is skipped.
DEFAULT_HISTORY_DAYS = 120


def md5_hex(value: str) -> str:
    """Return the lowercase hex MD5 of ``value``.

    The portal hashes the password client-side with blueimp-md5 before sending
    it; ``hashlib.md5`` produces the identical lowercase hex digest.
    """
    return hashlib.md5(value.encode("utf-8")).hexdigest()  # noqa: S324 - portal protocol


def _encode_request_para(params: Mapping[str, Any]) -> str:
    """Serialise ``params`` the way the portal's web client does."""
    payload = json.dumps(params, ensure_ascii=False, separators=(",", ":"))
    return payload.replace("+", "%2B").replace("&", "%26")


def _extract_token(data: Any) -> str | None:
    """Pull the auth token out of a login response."""
    if not isinstance(data, Mapping):
        return None
    if data.get("token"):
        return str(data["token"])
    user_info = data.get("userInfo")
    if isinstance(user_info, Mapping) and user_info.get("token"):
        return str(user_info["token"])
    return None


class ZSWaterClient:
    """Async client for the Zhongshan Water online portal."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        *,
        token: str | None = None,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        self._session = session
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self.token = token

    # ------------------------------------------------------------ plumbing

    def _payload(self, params: Mapping[str, Any] | None) -> dict[str, Any]:
        """Merge the portal's mandatory params *over* the caller's."""
        payload: dict[str, Any] = dict(params or {})
        payload.update(COMMON_PARAMS)
        payload["apiType"] = COMMON_PARAMS["apiType"]
        payload["appVersion"] = APP_VERSION
        payload["token"] = self.token
        return payload

    async def _async_request(
        self,
        method: str,
        path: str,
        params: Mapping[str, Any] | None = None,
    ) -> Any:
        """Perform one portal call and unwrap the JSON envelope."""
        payload = self._payload(params)
        url = f"{BASE_URL}{path}"
        try:
            if method == "GET":
                kwargs: dict[str, Any] = {
                    "params": {REQUEST_PARA_FIELD: json.dumps(payload, ensure_ascii=False)}
                }
            else:
                kwargs = {
                    "data": f"{REQUEST_PARA_FIELD}={_encode_request_para(payload)}",
                    "headers": {"Content-Type": CONTENT_TYPE},
                }
            async with self._session.request(
                method, url, timeout=self._timeout, **kwargs
            ) as response:
                if response.status != 200:
                    body = await response.text()
                    _LOGGER.debug(
                        "ZSWater %s %s -> HTTP %s: %s",
                        method,
                        path,
                        response.status,
                        body[:200],
                    )
                    raise ZSWaterApiError(
                        f"HTTP {response.status} from {path}", status=response.status
                    )
                body = await response.json(content_type=None)
        except ZSWaterApiError:
            raise
        except (aiohttp.ClientError, TimeoutError) as err:
            raise ZSWaterTransportError(f"{method} {path} failed: {err}") from err
        except (ValueError, json.JSONDecodeError) as err:
            raise ZSWaterTransportError(
                f"{method} {path} returned a non-JSON body"
            ) from err

        if not isinstance(body, Mapping):
            raise ZSWaterTransportError(f"{method} {path} returned {type(body).__name__}")

        status = body.get("status")
        if status == STATUS_NOT_LOGGED_IN:
            raise ZSWaterAuthError(
                str(body.get("message") or "登录状态已失效，请重新登录")
            )
        if status != STATUS_OK:
            raise ZSWaterApiError(
                str(body.get("message") or body.get("errmsg") or f"status={status}"),
                status=status if isinstance(status, int) else None,
                errcode=body.get("errcode"),
                payload=body,
            )
        return body.get("data")

    # --------------------------------------------------------------- auth

    async def async_send_sms_code(
        self, mobile: str, code_type: int = SMS_TYPE_VERIFY
    ) -> str:
        """Ask the portal to text a 短信验证码 to ``mobile``.

        ``code_type`` is ``1`` for registration, ``2`` for logging in and for
        verifying a phone number, and ``7`` for the general identity-check
        flows. Returns the operator's own message, normally 验证码发送成功.
        """
        data = await self._async_request(
            "GET", PATH_SEND_AUTH_CODE, {"mobile": mobile, "type": code_type}
        )
        if isinstance(data, Mapping):
            return str(data.get("message") or "验证码已发送")
        return "验证码已发送"

    async def async_login(
        self,
        mobile: str,
        password: str,
        sms_code: str | int,
        timestamp: int | str | None = None,
    ) -> Mapping[str, Any]:
        """Log in with 手机号 + 短信验证码 + 密码.

        This mirrors the portal's own login form, which pairs a 手机号 field, a
        「获取手机验证码」 button and a 手机验证码 field named ``code``; the
        password is sent as lowercase hex MD5. ``timestamp`` is the value the
        form keeps alongside its (unrendered) captcha state and is optional.

        Returns the portal's ``data`` block, which carries ``userInfo.token``.
        """
        params: dict[str, Any] = {
            "meterPhone": mobile,
            "userName": mobile,
            "password": md5_hex(password),
            "code": sms_code,
        }
        if timestamp is not None:
            params["timestamp"] = timestamp
        data = await self._async_request("POST", PATH_LOGIN, params)
        self._adopt_token(data)
        return data if isinstance(data, Mapping) else {}

    async def async_login_with_unionid(self, unionid: str) -> Mapping[str, Any]:
        """Log in by WeChat ``unionid``.

        This is the route the 微信公众号 uses: arriving from the public account
        leaves a ``unionid`` in the portal URL, which the portal exchanges here
        for a session token.
        """
        data = await self._async_request(
            "POST", PATH_WECHAT_LOGIN, {"unionid": unionid}
        )
        self._adopt_token(data)
        return data if isinstance(data, Mapping) else {}

    async def async_register(
        self,
        mobile: str,
        password: str,
        sms_code: str,
        unionid: str | None = None,
    ) -> Mapping[str, Any]:
        """Create a portal account with 手机号 + 短信验证码 + 密码.

        Passing ``unionid`` selects the WeChat registration command; without it
        the plain web command is used. On success the account is already logged
        in and the token is adopted.
        """
        params: dict[str, Any] = {
            "command": REGISTER_COMMAND_WECHAT if unionid else "30008.206",
            "authCode": sms_code,
            "phone": mobile,
            "password": md5_hex(password),
            "promoCode": "",
        }
        if unionid:
            params["unionid"] = unionid
        data = await self._async_request("POST", PATH_REGISTER, params)
        self._adopt_token(data)
        return data if isinstance(data, Mapping) else {}

    async def async_verify_login(self) -> bool:
        """Return ``True`` when the stored token still works."""
        try:
            await self.async_get_accounts()
        except ZSWaterAuthError:
            return False
        return True

    def _adopt_token(self, data: Any) -> None:
        token = _extract_token(data)
        if token is None:
            raise ZSWaterAuthError(
                "登录响应中没有 token，请检查账号或验证码"
            )
        self.token = token

    # -------------------------------------------------------- meter lookup

    async def async_get_accounts(self) -> list[WaterAccount]:
        """Return every 户号 bound to the logged-in account."""
        data = await self._async_request("POST", PATH_METER_LIST, {"UNID": ""})
        return parse_meter_list(data if isinstance(data, Sequence) else [])

    async def async_get_meter_detail(
        self,
        meter_number: str,
        meter_name: str | None = None,
        *,
        id_card: str | None = None,
        phone: str | None = None,
    ) -> MeterDetail | None:
        """Return 本期/上期抄表读数 and 抄表日 for one 户号."""
        data = await self._async_request(
            "POST",
            PATH_METER_INFO,
            {
                "userID": meter_number,
                "meterName": meter_name or "",
                "code": None,
                "meterIdCard": id_card or "",
                "meterPhone": phone or "",
            },
        )
        if isinstance(data, Sequence) and data and isinstance(data[0], Mapping):
            return MeterDetail.from_api(data[0])
        return None

    async def async_search_meter(
        self, meter_number: str, meter_name: str = ""
    ) -> str | None:
        """Look up the service address for a 户号 before binding it."""
        data = await self._async_request(
            "POST",
            PATH_METER_SEARCH,
            {"userID": meter_number, "meterName": meter_name},
        )
        if isinstance(data, Sequence) and data and isinstance(data[0], Mapping):
            address = data[0].get("address")
            return str(address) if address else None
        return None

    async def async_bind_meter(
        self,
        meter_number: str,
        meter_name: str,
        *,
        phone: str,
        address: str | None = None,
        verify_code: str = "777777",
        alert: int = 0,
        nickname: str = "",
    ) -> Any:
        """Bind an additional 户号 to the logged-in account."""
        return await self._async_request(
            "POST",
            PATH_METER_ADD,
            {
                "meterName": meter_name,
                "meterNumber": meter_number,
                "meterMobile": phone,
                "meterAlert": alert,
                "meterNick": nickname,
                "code": verify_code,
                "waterCorpId": COMMON_PARAMS["waterCorpId"],
                "meterAddress": address or "",
            },
        )

    async def async_check_phone_code(self, code: str, meter_phone: str) -> bool:
        """Verify a 短信验证码 sent for the 户号-binding flow."""
        data = await self._async_request(
            "POST", PATH_CHECK_PHONE_CODE, {"code": code, "meterPhone": meter_phone}
        )
        if isinstance(data, Mapping):
            return str(data.get("status", "0")) == "0"
        return True

    # ---------------------------------------------------------- billing

    async def async_get_readings(
        self,
        meter_number: str,
        *,
        days: int = DEFAULT_HISTORY_DAYS,
        end: date | None = None,
        pay_status: int | None = None,
    ) -> list[MeterReading]:
        """Return billing periods for one 户号, newest first."""
        end_date = end or date.today()
        start_date = end_date - timedelta(days=days)
        params: dict[str, Any] = {
            "meterNumber": meter_number,
            "startDate": start_date.strftime("%Y%m%d"),
            "endDate": end_date.strftime("%Y%m%d"),
        }
        if pay_status is not None:
            params["payStatus"] = pay_status
        data = await self._async_request("POST", PATH_PAY_HISTORY, params)
        return parse_readings(data)

    async def async_get_hang_records(
        self, meter_number: str, year: int | None = None
    ) -> list[MeterReading]:
        """Return the per-year 行水记录 (readings, 增减水量 and 阶梯 fields)."""
        target = year or date.today().year
        data = await self._async_request(
            "POST",
            PATH_HANG_RECORD,
            {
                "meterNumber": meter_number,
                "userNo": meter_number,
                "startDate": f"{target}0101",
                "endDate": f"{target}1231",
                "payStatus": 1,
            },
        )
        return parse_readings(data)

    async def async_get_bill_details(self, bill_number: str, is_charge: Any = None) -> Any:
        """Return the itemised 欠费明细 for a bill number."""
        return await self._async_request(
            "POST",
            PATH_BILL_PAY_INFO,
            {
                "waterCorpId": COMMON_PARAMS["waterCorpId"],
                "billno": bill_number,
                "ischarge": is_charge,
            },
        )
