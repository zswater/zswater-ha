"""Transport tests for the Zhongshan Water client.

These lock down the wire contract: the ``requestPara`` encoding, the params the
portal injects over the caller's, and the ``status``-based error mapping.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "custom_components" / "zswater"))

from zswater_client import ZSWaterClient, md5_hex  # noqa: E402
from zswater_client.const import (  # noqa: E402
    APP_VERSION,
    BASE_URL,
    PATH_METER_LIST,
    PATH_PAY_HISTORY,
    PATH_SEND_AUTH_CODE,
    STATUS_NOT_LOGGED_IN,
)
from zswater_client.exceptions import (  # noqa: E402
    ZSWaterApiError,
    ZSWaterAuthError,
    ZSWaterTransportError,
)

OK_ENVELOPE = {"status": 0, "errcode": 0, "errmsg": "", "message": "", "data": []}


class FakeResponse:
    def __init__(self, status: int, payload: Any = None, body: bytes = b"") -> None:
        self.status = status
        self._payload = payload
        self._body = body

    async def __aenter__(self) -> "FakeResponse":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def json(self, content_type: str | None = None) -> Any:
        if self._payload is None:
            raise ValueError("not json")
        return self._payload

    async def text(self) -> str:
        return self._body.decode("utf-8", "replace")

    async def read(self) -> bytes:
        return self._body


class FakeSession:
    """Records calls and replays a queued response."""

    def __init__(self, payload: Any = OK_ENVELOPE, status: int = 200) -> None:
        self.payload = payload
        self.status = status
        self.calls: list[dict[str, Any]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"method": method, "url": url, **kwargs})
        return FakeResponse(self.status, self.payload)

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"method": "GET", "url": url, **kwargs})
        return FakeResponse(self.status, self.payload, body=b"\x89PNG")


def test_md5_hex_matches_the_portal_algorithm() -> None:
    # blueimp-md5's default export is the lowercase hex digest.
    assert md5_hex("123456") == "e10adc3949ba59abbe56e057f20f883e"
    assert md5_hex("password") == "5f4dcc3b5aa765d61d8327deb882cf99"


@pytest.mark.asyncio
async def test_post_sends_a_raw_json_form_field() -> None:
    session = FakeSession()
    client = ZSWaterClient(session, token="TOKEN")

    await client.async_get_accounts()

    call = session.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == f"{BASE_URL}{PATH_METER_LIST}"
    assert call["headers"]["Content-Type"] == "application/x-www-form-urlencoded"

    body = call["data"]
    assert body.startswith("requestPara={")
    # The portal sends raw JSON; only ``+`` and ``&`` are escaped.
    payload = json.loads(body.removeprefix("requestPara="))
    assert payload["UNID"] == ""
    assert payload["waterCorpId"] == 3
    assert payload["apiType"] == "JSAPI"
    assert payload["appVersion"] == APP_VERSION
    assert payload["token"] == "TOKEN"


@pytest.mark.asyncio
async def test_common_params_win_over_caller_params() -> None:
    session = FakeSession()
    client = ZSWaterClient(session, token="TOKEN")

    # A caller must not be able to break the portal contract by passing its own
    # apiType/waterCorpId — the web client overwrites them too.
    await client._async_request(
        "POST", PATH_METER_LIST, {"apiType": "PC", "waterCorpId": 99}
    )

    payload = json.loads(session.calls[0]["data"].removeprefix("requestPara="))
    assert payload["apiType"] == "JSAPI"
    assert payload["waterCorpId"] == 3


@pytest.mark.asyncio
async def test_plus_and_ampersand_are_escaped() -> None:
    session = FakeSession()
    client = ZSWaterClient(session, token="T")

    await client._async_request("POST", PATH_METER_LIST, {"note": "a+b&c"})

    body = session.calls[0]["data"]
    assert "%2B" in body
    assert "%26" in body
    assert "a+b" not in body


@pytest.mark.asyncio
async def test_get_uses_a_request_para_query_parameter() -> None:
    session = FakeSession()
    client = ZSWaterClient(session, token=None)

    await client.async_send_sms_code("13800000000")

    call = session.calls[0]
    assert call["method"] == "GET"
    assert call["url"] == f"{BASE_URL}{PATH_SEND_AUTH_CODE}"
    payload = json.loads(call["params"]["requestPara"])
    assert payload["mobile"] == "13800000000"
    assert payload["type"] == 1
    assert payload["token"] is None


@pytest.mark.asyncio
async def test_status_11_means_the_token_is_gone() -> None:
    session = FakeSession({"status": STATUS_NOT_LOGGED_IN, "message": "请重新登录"})
    client = ZSWaterClient(session, token="STALE")

    with pytest.raises(ZSWaterAuthError):
        await client.async_get_accounts()


@pytest.mark.asyncio
async def test_business_error_carries_the_operator_message() -> None:
    session = FakeSession({"status": 7, "errcode": 200046, "message": "网络异常,请稍后再试!"})
    client = ZSWaterClient(session, token="TOKEN")

    with pytest.raises(ZSWaterApiError) as err:
        await client.async_get_accounts()

    assert err.value.status == 7
    assert err.value.errcode == 200046
    assert "网络异常" in str(err.value)


@pytest.mark.asyncio
async def test_http_500_is_reported_not_swallowed() -> None:
    session = FakeSession({"status": 0}, status=500)
    client = ZSWaterClient(session, token="TOKEN")

    with pytest.raises(ZSWaterApiError):
        await client.async_get_accounts()


@pytest.mark.asyncio
async def test_non_json_body_is_a_transport_error() -> None:
    session = FakeSession(payload=None)
    client = ZSWaterClient(session, token="TOKEN")

    with pytest.raises(ZSWaterTransportError):
        await client.async_get_accounts()


@pytest.mark.asyncio
async def test_password_login_adopts_userinfo_token() -> None:
    session = FakeSession(
        {
            "status": 0,
            "data": {"userInfo": {"token": "NEW-TOKEN", "usermobile": "13800000000"}},
        }
    )
    client = ZSWaterClient(session)

    await client.async_login_with_password("13800000000", "123456", "8421", "1700000000000")

    assert client.token == "NEW-TOKEN"
    payload = json.loads(session.calls[0]["data"].removeprefix("requestPara="))
    assert payload["meterPhone"] == "13800000000"
    assert payload["userName"] == "13800000000"
    assert payload["password"] == md5_hex("123456")
    assert payload["code"] == "8421"
    assert payload["timestamp"] == "1700000000000"


@pytest.mark.asyncio
async def test_login_without_a_token_fails_loudly() -> None:
    session = FakeSession({"status": 0, "data": {"userInfo": {}}})
    client = ZSWaterClient(session)

    with pytest.raises(ZSWaterAuthError):
        await client.async_login_with_password("13800000000", "pw", "1", "1")


@pytest.mark.asyncio
async def test_unionid_login_sends_only_the_unionid() -> None:
    session = FakeSession({"status": 0, "data": {"userInfo": {"token": "T"}}})
    client = ZSWaterClient(session)

    await client.async_login_with_unionid("oABC-123")

    payload = json.loads(session.calls[0]["data"].removeprefix("requestPara="))
    assert payload["unionid"] == "oABC-123"
    assert client.token == "T"


@pytest.mark.asyncio
async def test_reading_history_window_is_yyyymmdd() -> None:
    session = FakeSession({"status": 0, "data": []})
    client = ZSWaterClient(session, token="T")

    await client.async_get_readings("1234567890", days=30)

    payload = json.loads(session.calls[0]["data"].removeprefix("requestPara="))
    assert session.calls[0]["url"] == f"{BASE_URL}{PATH_PAY_HISTORY}"
    assert payload["meterNumber"] == "1234567890"
    assert len(payload["startDate"]) == 8 and payload["startDate"].isdigit()
    assert len(payload["endDate"]) == 8 and payload["endDate"].isdigit()
    assert payload["startDate"] < payload["endDate"]
    assert "payStatus" not in payload


@pytest.mark.asyncio
async def test_captcha_returns_raw_bytes() -> None:
    session = FakeSession()
    client = ZSWaterClient(session)

    image = await client.async_get_captcha("1700000000000")

    assert image.startswith(b"\x89PNG")
    assert session.calls[0]["params"] == {"timestamp": "1700000000000"}
