"""Parsing tests for the Zhongshan Water client models.

The payloads below are shaped like the real portal responses: the account list
uses camelCase money keys, billing rows use ``costDate``/``currentRead``, and
the 欠费明细 collection uses Chinese keys.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "custom_components" / "zswater"))

from zswater_client.models import (  # noqa: E402
    MeterDetail,
    MeterReading,
    MeterSnapshot,
    WaterAccount,
    parse_meter_list,
    parse_readings,
)

ACCOUNT_PAYLOAD = {
    "meterNumber": "1234567890",
    "meterName": "张三",
    "meterAddress": "中山市石岐区某路1号",
    "area": 1,
    "balance": "12.30",
    "fullAmount": "45.60",
    "arrearage": 45.6,
    "cardstatustxt": "正常",
    "watertypetxt": "居民生活用水",
}

DETAIL_PAYLOAD = {
    "lastto": "1200",
    "nextto": "1234",
    "lastreaddate": "20260801",
    "nextreaddate": "2026-09-01",
    "hosttelno": "13800000000",
    "isjtyh": "1",
    "onesurplus": "18.5",
    "twosurplus": "0",
}

READING_PAYLOADS = [
    {
        "costDate": "20260901",
        "lastRead": 1200,
        "currentRead": 1234,
        "consumedVolume": 34,
        "defaultAmount": 45.6,
        "penalty": 0.0,
        "payablePrincipal": 45.6,
        "payStatus": "欠费",
        "paymentDate": None,
    },
    {
        "costDate": "20260801",
        "lastRead": 1170,
        "currentRead": 1200,
        "consumedVolume": 30,
        "defaultAmount": 40.0,
        "penalty": 0.5,
        "payablePrincipal": 40.5,
        "payStatus": "已销帐",
        "paymentDate": "20260815",
    },
]

# The 行水记录 endpoint renames the same concepts.
HANG_PAYLOAD = {
    "feeInfo": [
        {
            "bqcbr": "20260901",
            "sqxz": 1200,
            "bqxz": 1234,
            "znj": "1.20",
            "fyztms": "已销帐",
        }
    ]
}


def test_water_account_parses_money_and_context() -> None:
    account = WaterAccount.from_api(ACCOUNT_PAYLOAD)

    assert account.meter_number == "1234567890"
    assert account.name == "张三"
    assert account.address == "中山市石岐区某路1号"
    assert account.balance == 12.30
    assert account.arrears == 45.60
    assert account.current_bill == 45.60
    assert account.status == "正常"
    assert account.water_type == "居民生活用水"


def test_water_account_accepts_chinese_keys() -> None:
    account = WaterAccount.from_api({"户号": "998877", "户名": "李四"})

    assert account.meter_number == "998877"
    assert account.name == "李四"


def test_water_account_requires_a_number() -> None:
    try:
        WaterAccount.from_api({"meterName": "无户号"})
    except ValueError:
        return
    raise AssertionError("an account without a 户号 must be rejected")


def test_meter_detail_maps_next_to_current_reading() -> None:
    detail = MeterDetail.from_api(DETAIL_PAYLOAD)

    # ``nextto``/``nextreaddate`` are the period being billed now (本期).
    assert detail.current_reading == 1234.0
    assert detail.last_reading == 1200.0
    assert detail.current_read_date == "2026-09-01"
    assert detail.last_read_date == "2026-08-01"
    assert detail.is_tiered is True
    assert detail.tier1_remaining == 18.5


def test_readings_are_sorted_newest_first() -> None:
    readings = parse_readings(list(reversed(READING_PAYLOADS)))

    assert [r.cost_date for r in readings] == ["2026-09-01", "2026-08-01"]
    assert readings[0].consumed_volume == 34.0
    assert readings[0].pay_status == "欠费"


def test_hang_record_wrapper_is_unwrapped() -> None:
    readings = parse_readings(HANG_PAYLOAD)

    assert len(readings) == 1
    assert readings[0].cost_date == "2026-09-01"
    assert readings[0].last_read == 1200.0
    assert readings[0].current_read == 1234.0
    assert readings[0].penalty == 1.20
    assert readings[0].pay_status == "已销帐"


def test_parse_readings_tolerates_garbage() -> None:
    assert parse_readings(None) == []
    assert parse_readings("not a list") == []
    assert parse_readings([{"costDate": None}, "junk"])[0].cost_date is None


def test_parse_meter_list_skips_entries_without_a_number() -> None:
    accounts = parse_meter_list([ACCOUNT_PAYLOAD, {"meterName": "无户号"}, "junk"])

    assert [a.meter_number for a in accounts] == ["1234567890"]


def _snapshot() -> MeterSnapshot:
    account = WaterAccount.from_api(ACCOUNT_PAYLOAD)
    return MeterSnapshot(
        account=account,
        detail=MeterDetail.from_api(DETAIL_PAYLOAD),
        readings=parse_readings(READING_PAYLOADS),
    )


def test_snapshot_readings_come_from_the_meter_detail() -> None:
    snapshot = _snapshot()

    assert snapshot.current_reading == 1234.0
    assert snapshot.last_reading == 1200.0
    assert snapshot.current_read_date == "2026-09-01"
    # 上期抄表日 has no meter-detail source, so it falls back to the previous row.
    assert snapshot.last_read_date == "2026-08-01"


def test_snapshot_falls_back_to_billing_rows_without_detail() -> None:
    account = WaterAccount.from_api(ACCOUNT_PAYLOAD)
    snapshot = MeterSnapshot(
        account=account, detail=None, readings=parse_readings(READING_PAYLOADS)
    )

    assert snapshot.current_reading == 1234.0
    assert snapshot.last_reading == 1200.0
    assert snapshot.usage == 34.0
    assert snapshot.water_fee == 45.6
    assert snapshot.payable == 45.6


def test_snapshot_derives_usage_when_the_portal_omits_it() -> None:
    account = WaterAccount.from_api(ACCOUNT_PAYLOAD)
    snapshot = MeterSnapshot(
        account=account,
        readings=parse_readings(
            [{"costDate": "20260901", "lastRead": 1200, "currentRead": 1234.5}]
        ),
    )

    assert snapshot.usage == 34.5


def test_snapshot_money_and_arrears_flag() -> None:
    snapshot = _snapshot()

    assert snapshot.arrears == 45.60
    assert snapshot.balance == 12.30
    assert snapshot.has_arrears is True

    paid_off = WaterAccount.from_api({**ACCOUNT_PAYLOAD, "fullAmount": "0"})
    assert MeterSnapshot(account=paid_off).has_arrears is False


def test_snapshot_unknown_arrears_is_not_reported_as_paid() -> None:
    account = WaterAccount.from_api({"meterNumber": "1"})

    assert MeterSnapshot(account=account).has_arrears is None


def test_snapshot_history_serialises_every_period() -> None:
    history = _snapshot().history

    assert len(history) == 2
    assert history[0]["cost_date"] == "2026-09-01"
    assert history[1]["payment_date"] == "2026-08-15"
