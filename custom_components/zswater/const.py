"""Constants for the Zhongshan Water (中山公用水务) integration."""

from __future__ import annotations

from datetime import timedelta

from .zswater_client import LoginType

DOMAIN = "zswater"

# ------------------------------------------------------------------ config

#: 登录手机号
CONF_ACCOUNT_NUMBER = "account_number"
CONF_LOGIN_TYPE = "login_type"
CONF_AUTH_TOKEN = "auth_token"
#: 户号 bound to this entry: ``{meter_number: {...}}``
CONF_WATER_ACCOUNTS = "accounts"
CONF_UPDATE_INTERVAL = "update_interval"
CONF_IP_FAMILY = "ip_family"
CONF_SETTINGS = "settings"
CONF_UPDATED_AT = "updated_at"
CONF_ACTION = "action"
CONF_SMS_CODE = "sms_code"
CONF_HISTORY_DAYS = "history_days"
CONF_METER_NUMBER = "meter_number"
CONF_METER_NAME = "meter_name"
CONF_METER_PHONE = "meter_phone"
CONF_METER_ADDRESS = "meter_address"

# -------------------------------------------------------------------- steps

STEP_NETWORK = "network"
STEP_USER = "user"
#: 手机号 + 密码; submitting this step texts the 短信验证码.
STEP_CREDENTIALS = "credentials"
#: 短信验证码; submitting this step logs in.
STEP_SMS_CODE = "sms_code"
STEP_INIT = "init"
STEP_SETTINGS = "settings"
STEP_ADD_ACCOUNT = "add_account"
STEP_ADD_ACCOUNT_VERIFY = "add_account_verify"
STEP_REAUTH = "reauth"

ABORT_NO_ACCOUNT = "no_account"
ABORT_ALL_ADDED = "all_added"
ABORT_SINGLE_INSTANCE = "single_instance_allowed"

# ------------------------------------------------------------------- errors

ERROR_CANNOT_CONNECT = "cannot_connect"
ERROR_INVALID_AUTH = "invalid_auth"
ERROR_UNKNOWN = "unknown"
ERROR_NO_SMS_CODE = "no_sms_code"
ERROR_SMS_CODE_INVALID = "sms_code_invalid"

# --------------------------------------------------------------- sensor keys

SUFFIX_ARREARS = "arrears"
SUFFIX_CURRENT_BILL = "current_bill"
SUFFIX_BALANCE = "balance"
SUFFIX_LAST_READING = "last_reading"
SUFFIX_CURRENT_READING = "current_reading"
SUFFIX_USAGE = "usage"
SUFFIX_WATER_FEE = "water_fee"
SUFFIX_PENALTY = "penalty"
SUFFIX_PAYABLE = "payable"
SUFFIX_LAST_READ_DATE = "last_read_date"
SUFFIX_CURRENT_READ_DATE = "current_read_date"
SUFFIX_HISTORY = "history"

SUFFIX_HAS_ARREARS = "has_arrears"

#: Attribute keys exposed by the sensors.
ATTR_KEY_METER_NUMBER = "meter_number"
ATTR_KEY_METER_NAME = "meter_name"
ATTR_KEY_ADDRESS = "address"
ATTR_KEY_ACCOUNT_STATUS = "account_status"
ATTR_KEY_HISTORY = "history"
ATTR_KEY_TIER1_REMAINING = "tier1_remaining"
ATTR_KEY_TIER2_REMAINING = "tier2_remaining"
ATTR_KEY_IS_TIERED = "is_tiered"

# ------------------------------------------------------------------ defaults

#: 6 hours: water bills change at most daily, but 欠费 moves as soon as a
#: payment lands, so a tighter default than the monthly cadence is useful.
DEFAULT_UPDATE_INTERVAL = int(timedelta(hours=6).total_seconds())
MIN_UPDATE_INTERVAL = 60
#: How much billing history to pull per 户号.
DEFAULT_HISTORY_DAYS = 120
#: Per-request timeout handed to the client.
SETTING_UPDATE_TIMEOUT = 30

IP_FAMILY_AUTO = "auto"
IP_FAMILY_IPV4 = "ipv4"
IP_FAMILY_IPV6 = "ipv6"
IP_FAMILY_OPTIONS = (IP_FAMILY_AUTO, IP_FAMILY_IPV4, IP_FAMILY_IPV6)
DEFAULT_IP_FAMILY = IP_FAMILY_AUTO

#: Portal entry point, quoted in the config-flow help text.
PORTAL_URL = "https://smartbi.zsws.com.cn/"
