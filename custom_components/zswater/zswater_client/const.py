"""API constants for the Zhongshan Water (中山公用水务) online portal.

Every value in this module was derived from the production web client served at
``https://smartbi.zsws.com.cn`` (``/js/main.*.js``), not from guesswork. If the
portal is re-released, re-check that bundle before changing anything here.
"""

from __future__ import annotations

from enum import StrEnum

# ---------------------------------------------------------------- transport

#: Portal origin. All API paths below are relative to this host.
BASE_URL = "https://smartbi.zsws.com.cn"

#: Prefix used by the "manager" (back office) endpoints.
IWATERMGR = "/iwatermgr"

#: Values injected into *every* API payload by the web client's ajax wrapper.
#: The wrapper merges them *over* the caller's own params, so callers cannot
#: override them.
COMMON_PARAMS: dict[str, object] = {
    "waterCorpId": 3,
    "UNID": "",
    "areaId": 0,
    "accountType": "XJ",
    "apiType": "JSAPI",
}

#: Reported client version; the portal echoes it back into some responses.
APP_VERSION = "1.0.2"

#: Name of the form field carrying the JSON payload on POST requests.
REQUEST_PARA_FIELD = "requestPara"

#: The portal wraps every request in this content type.
CONTENT_TYPE = "application/x-www-form-urlencoded"

DEFAULT_TIMEOUT = 30

# ---------------------------------------------------------------- endpoints

PATH_CAPTCHA = "/iwater/nt/validateCode.json"
PATH_LOGIN = "/iwater/nt/wt/login.json"
PATH_WECHAT_LOGIN = "/iwater/nt/wt/logining.json"
PATH_SSO_LOGIN = "/iwater/sso/login.json"
PATH_SSO_REGISTER = "/iwater/sso/register.json"
PATH_REGISTER = "/iwater/iwaterapi/nt.json"
PATH_SEND_AUTH_CODE = "/iwater/v1/usercenter/nt/sendAuthCode/v4.json"
PATH_CHANGE_PASSWORD = "/iwater/v1/user/nt/updatepassword/v1.json"

PATH_METER_LIST = "/iwater/v1/watermeter/queryUserMeterList/v1.json"
PATH_METER_INFO = "/iwater/v1/watermeter/getMeterInfoByUId/v1.json"
PATH_METER_SEARCH = "/iwater/v1/watermeter/searchMeterInfoByUId/v1.json"
PATH_METER_ADD = "/iwater/v1/watermeter/addMeter/v2.json"
PATH_METER_DELETE = "/iwater/v1/watermeter/deleteMeter/v1.json"
PATH_CHECK_PHONE_CODE = "/iwater/v1/watermeter/checkPhoneCode/v1.json"
PATH_PAY_HISTORY = "/iwater/v1/watermeter/queryPayMentInfo/v2.json"
PATH_BILL_PAY_INFO = "/iwater/v1/watermeter/queryBillPayInfo.json"

PATH_METER_NO_LIST = "/iwater/memeterinfo/getMeterNoListV2.json"
PATH_HANG_RECORD = "/iwater/memeterinfo/getHangShuiRecord.json"
PATH_ORDER_RECORD = "/iwater/meterpay/getOrderRecordDetail.json"

# ---------------------------------------------------------------- sms codes

#: ``type`` values accepted by ``PATH_SEND_AUTH_CODE``.
SMS_TYPE_REGISTER = 1
SMS_TYPE_BIND_METER = 2
SMS_TYPE_GENERAL = 7

# ------------------------------------------------------------- registration

#: ``command`` values accepted by ``PATH_REGISTER``.
REGISTER_COMMAND_WEB = "30008.206"
REGISTER_COMMAND_WECHAT = "30008.207"

# ------------------------------------------------------- response envelope

#: ``status`` values returned inside the JSON envelope. Anything other than
#: ``STATUS_OK`` means the call failed even when HTTP returned 200, and a few
#: endpoints answer with HTTP 500 instead of an envelope on bad input.
STATUS_OK = 0
STATUS_PARAM_ERROR = 7
STATUS_NOT_LOGGED_IN = 11


class LoginType(StrEnum):
    """How the stored auth token was obtained."""

    PASSWORD = "password"
    WECHAT = "wechat"
    SMS = "sms"


#: ``type`` field used by the portal when logging in, per login route.
LOGIN_TYPE_DESCRIPTIONS: dict[str, str] = {
    LoginType.PASSWORD: "手机号 + 密码 + 图形验证码",
    LoginType.WECHAT: "微信 unionid（公众号/扫码）",
    LoginType.SMS: "手机号 + 短信验证码（注册）",
}
