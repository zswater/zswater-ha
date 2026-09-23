"""Typed views over the JSON returned by the Zhongshan Water portal.

The portal mixes two naming conventions in the same payloads: some collections
use camelCase keys (``meterNumber``, ``fullAmount``) while the arrears-detail
collection uses Chinese keys (``户号``, ``金额``). Every parser below therefore
reads through a fallback chain instead of a single key, so a payload that
switches convention does not silently turn into ``None``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Mapping, Sequence

# ------------------------------------------------------------------ helpers


def _first(source: Mapping[str, Any], *keys: str) -> Any:
    """Return the first present, non-empty value among ``keys``."""
    for key in keys:
        if key in source:
            value = source[key]
            if value is not None and value != "":
                return value
    return None


def _to_float(value: Any) -> float | None:
    """Coerce the portal's numbers to ``float``, tolerating ``¥`` and blanks."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "").replace("¥", "").replace("￥", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _to_str(value: Any) -> str | None:
    """Return a stripped string, or ``None`` when there is nothing to show."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_date(value: Any) -> str | None:
    """Normalise ``YYYYMMDD`` / ISO / epoch-millis values to ``YYYY-MM-DD``."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        # The portal sends epoch milliseconds for some timestamps.
        try:
            return datetime.fromtimestamp(value / 1000).date().isoformat()
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y%m%d", "%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y%m%d%H%M%S"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text).date().isoformat()
    except ValueError:
        return None


# ------------------------------------------------------------------- models


@dataclass(frozen=True, slots=True)
class WaterAccount:
    """One bound 户号 (water meter account) plus its money fields."""

    meter_number: str
    name: str | None = None
    address: str | None = None
    area: Any = None
    #: 账户余额
    balance: float | None = None
    #: 总欠费金额 —— ``fullAmount``
    arrears: float | None = None
    #: 本期账单 —— ``arrearage``
    current_bill: float | None = None
    #: 户号状态，例如 正常 / 停水 / 拆表
    status: str | None = None
    #: 用水类型
    water_type: str | None = None

    @classmethod
    def from_api(cls, payload: Mapping[str, Any]) -> "WaterAccount":
        """Build an account from one ``queryUserMeterList`` entry."""
        meter_number = _to_str(
            _first(payload, "meterNumber", "户号", "cardno", "userNo", "userID")
        )
        if meter_number is None:
            raise ValueError(f"meter account payload has no number: {payload!r}")
        return cls(
            meter_number=meter_number,
            name=_to_str(_first(payload, "meterName", "户名", "cardname")),
            address=_to_str(_first(payload, "meterAddress", "地址", "adress")),
            area=_first(payload, "area"),
            balance=_to_float(_first(payload, "balance", "账户余额")),
            arrears=_to_float(_first(payload, "fullAmount", "总欠费金额")),
            current_bill=_to_float(_first(payload, "arrearage", "本期账单")),
            status=_to_str(_first(payload, "cardstatustxt", "billStatus", "状态")),
            water_type=_to_str(_first(payload, "watertypetxt", "用水类型")),
        )

    @classmethod
    def from_stored(cls, payload: Mapping[str, Any]) -> "WaterAccount":
        """Rebuild an account from the config entry (already-normalised keys)."""
        return cls(
            meter_number=str(payload["meter_number"]),
            name=payload.get("name"),
            address=payload.get("address"),
            area=payload.get("area"),
            balance=_to_float(payload.get("balance")),
            arrears=_to_float(payload.get("arrears")),
            current_bill=_to_float(payload.get("current_bill")),
            status=payload.get("status"),
            water_type=payload.get("water_type"),
        )

    def as_stored(self) -> dict[str, Any]:
        """Serialise for ``ConfigEntry.data``."""
        return {
            "meter_number": self.meter_number,
            "name": self.name,
            "address": self.address,
            "area": self.area,
        }

    def with_money_fields(self, fresh: "WaterAccount") -> "WaterAccount":
        """Return a copy carrying ``fresh``'s live money/status fields."""
        return WaterAccount(
            meter_number=self.meter_number,
            name=fresh.name or self.name,
            address=fresh.address or self.address,
            area=fresh.area if fresh.area is not None else self.area,
            balance=fresh.balance,
            arrears=fresh.arrears,
            current_bill=fresh.current_bill,
            status=fresh.status,
            water_type=fresh.water_type or self.water_type,
        )


@dataclass(frozen=True, slots=True)
class MeterDetail:
    """Meter-level detail from ``getMeterInfoByUId``.

    Note the portal's naming: ``next*`` means *the reading being billed now*
    (本期) and ``last*`` the one before it (上期).
    """

    #: 上期抄表读数 —— ``lastto``
    last_reading: float | None = None
    #: 本期抄表读数 —— ``nextto``
    current_reading: float | None = None
    #: 上期抄表日 —— ``lastreaddate``
    last_read_date: str | None = None
    #: 本期抄表日 —— ``nextreaddate``
    current_read_date: str | None = None
    host_phone: str | None = None
    is_tiered: bool = False
    #: 阶梯一剩余水量
    tier1_remaining: float | None = None
    #: 阶梯二剩余水量
    tier2_remaining: float | None = None

    @classmethod
    def from_api(cls, payload: Mapping[str, Any]) -> "MeterDetail":
        """Build from ``data[0]`` of ``getMeterInfoByUId``."""
        return cls(
            last_reading=_to_float(_first(payload, "lastto", "上期行至")),
            current_reading=_to_float(_first(payload, "nextto", "本期行至")),
            last_read_date=_normalize_date(
                _first(payload, "lastreaddate", "上期抄表日")
            ),
            current_read_date=_normalize_date(
                _first(payload, "nextreaddate", "本期抄表日")
            ),
            host_phone=_to_str(_first(payload, "hosttelno")),
            is_tiered=str(_first(payload, "isjtyh") or "") == "1",
            tier1_remaining=_to_float(_first(payload, "onesurplus")),
            tier2_remaining=_to_float(_first(payload, "twosurplus")),
        )


@dataclass(frozen=True, slots=True)
class MeterReading:
    """One billing period of meter readings, usage and charges."""

    #: 抄表日期 / 费用日期
    cost_date: str | None = None
    #: 上期行至 (上期抄表读数)
    last_read: float | None = None
    #: 本期行至 (本期抄表读数)
    current_read: float | None = None
    #: 用水量, 立方米
    consumed_volume: float | None = None
    #: 水费, 元
    water_fee: float | None = None
    #: 违约金, 元
    penalty: float | None = None
    #: 应缴总金额, 元
    payable: float | None = None
    #: 缴费状况，例如 已销帐 / 欠费
    pay_status: str | None = None
    #: 缴费时间
    payment_date: str | None = None
    #: 已缴金额
    paid_amount: float | None = None
    #: 该笔费用仍在划帐中
    is_frozen: bool = False

    @classmethod
    def from_api(cls, payload: Mapping[str, Any]) -> "MeterReading":
        """Build from one ``queryPayMentInfo`` / ``getHangShuiRecord`` entry."""
        return cls(
            cost_date=_normalize_date(_first(payload, "costDate", "bqcbr", "费用日期")),
            last_read=_to_float(_first(payload, "lastRead", "sqxz", "上期行至")),
            current_read=_to_float(_first(payload, "currentRead", "bqxz", "本期行至")),
            consumed_volume=_to_float(_first(payload, "consumedVolume", "水量")),
            water_fee=_to_float(_first(payload, "defaultAmount", "水费")),
            penalty=_to_float(_first(payload, "penalty", "znj", "违约金")),
            payable=_to_float(_first(payload, "payablePrincipal", "总金额")),
            pay_status=_to_str(_first(payload, "payStatus", "fyztms", "费用状态")),
            payment_date=_normalize_date(_first(payload, "paymentDate", "缴费时间")),
            paid_amount=_to_float(_first(payload, "paidAmount")),
            is_frozen=str(_first(payload, "freezestatus") or "") == "1",
        )


@dataclass(slots=True)
class MeterSnapshot:
    """Everything the sensors need for a single 户号."""

    account: WaterAccount
    detail: MeterDetail | None = None
    #: Billing periods, newest first.
    readings: list[MeterReading] = field(default_factory=list)

    def _reading(self, index: int) -> MeterReading | None:
        if len(self.readings) > index:
            return self.readings[index]
        return None

    @property
    def latest(self) -> MeterReading | None:
        """The most recent billing period."""
        return self._reading(0)

    @property
    def previous(self) -> MeterReading | None:
        """The billing period before :attr:`latest`."""
        return self._reading(1)

    # -- money ------------------------------------------------------------

    @property
    def arrears(self) -> float | None:
        """欠费金额 —— account-level total, falling back to the latest bill."""
        if self.account.arrears is not None:
            return self.account.arrears
        latest = self.latest
        if latest is not None and latest.payable is not None:
            if latest.pay_status and "已" not in latest.pay_status:
                return latest.payable
        return None

    @property
    def balance(self) -> float | None:
        return self.account.balance

    @property
    def current_bill(self) -> float | None:
        if self.account.current_bill is not None:
            return self.account.current_bill
        latest = self.latest
        return latest.payable if latest is not None else None

    @property
    def has_arrears(self) -> bool | None:
        """``True`` when the account owes money."""
        arrears = self.arrears
        if arrears is None:
            return None
        return arrears > 0

    # -- readings ---------------------------------------------------------

    @property
    def current_reading(self) -> float | None:
        """本期抄表读数."""
        if self.detail is not None and self.detail.current_reading is not None:
            return self.detail.current_reading
        latest = self.latest
        return latest.current_read if latest is not None else None

    @property
    def last_reading(self) -> float | None:
        """上期抄表读数."""
        if self.detail is not None and self.detail.last_reading is not None:
            return self.detail.last_reading
        latest = self.latest
        if latest is not None and latest.last_read is not None:
            return latest.last_read
        previous = self.previous
        return previous.current_read if previous is not None else None

    @property
    def current_read_date(self) -> str | None:
        if self.detail is not None and self.detail.current_read_date is not None:
            return self.detail.current_read_date
        latest = self.latest
        return latest.cost_date if latest is not None else None

    @property
    def last_read_date(self) -> str | None:
        if self.detail is not None and self.detail.last_read_date is not None:
            return self.detail.last_read_date
        previous = self.previous
        return previous.cost_date if previous is not None else None

    # -- usage ------------------------------------------------------------

    @property
    def usage(self) -> float | None:
        """本期用水量, 立方米."""
        latest = self.latest
        if latest is None:
            return None
        if latest.consumed_volume is not None:
            return latest.consumed_volume
        if latest.current_read is not None and latest.last_read is not None:
            return round(latest.current_read - latest.last_read, 3)
        return None

    @property
    def water_fee(self) -> float | None:
        latest = self.latest
        return latest.water_fee if latest is not None else None

    @property
    def penalty(self) -> float | None:
        latest = self.latest
        return latest.penalty if latest is not None else None

    @property
    def payable(self) -> float | None:
        latest = self.latest
        return latest.payable if latest is not None else None

    @property
    def cost_date(self) -> str | None:
        latest = self.latest
        return latest.cost_date if latest is not None else None

    @property
    def status(self) -> str | None:
        return self.account.status

    @property
    def history(self) -> list[dict[str, Any]]:
        """Billing history for the ``history`` sensor attribute."""
        rows: list[dict[str, Any]] = []
        for reading in self.readings:
            rows.append(
                {
                    "cost_date": reading.cost_date,
                    "last_read": reading.last_read,
                    "current_read": reading.current_read,
                    "consumed_volume": reading.consumed_volume,
                    "water_fee": reading.water_fee,
                    "penalty": reading.penalty,
                    "payable": reading.payable,
                    "pay_status": reading.pay_status,
                    "payment_date": reading.payment_date,
                }
            )
        return rows


def parse_meter_list(payload: Sequence[Mapping[str, Any]] | None) -> list[WaterAccount]:
    """Parse a ``queryUserMeterList`` array, skipping entries without a 户号."""
    accounts: list[WaterAccount] = []
    for item in payload or ():
        try:
            accounts.append(WaterAccount.from_api(item))
        except (ValueError, AttributeError, TypeError):
            continue
    return accounts


def parse_readings(payload: Any) -> list[MeterReading]:
    """Parse a billing-history payload, newest first.

    ``getHangShuiRecord`` wraps its rows in ``data.feeInfo`` while
    ``queryPayMentInfo`` returns a bare array; accept both.
    """
    rows = payload
    if isinstance(payload, Mapping):
        rows = payload.get("feeInfo") or payload.get("list") or []
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        return []
    readings = []
    for item in rows:
        if not isinstance(item, Mapping):
            continue
        readings.append(MeterReading.from_api(item))
    readings.sort(key=lambda r: r.cost_date or date.min.isoformat(), reverse=True)
    return readings
