"""Standalone demo for :mod:`zswater_client` — no Home Assistant required.

Useful for checking whether the portal contract still holds after an update::

    # 1. ask the portal to text you a code
    python custom_components/zswater/zswater_client_demo.py --mobile 13800000000 --send-code

    # 2. sign in with the code and dump what the portal returns
    python custom_components/zswater/zswater_client_demo.py \\
        --mobile 13800000000 --password 'secret' --sms-code 123456

The login is 手机号 + 短信验证码 + 密码, mirroring the portal's own login card.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

import aiohttp

from zswater_client import SMS_TYPE_VERIFY, ZSWaterClient, ZSWaterError


async def _run(args: argparse.Namespace) -> int:
    async with aiohttp.ClientSession() as session:
        client = ZSWaterClient(session)

        if args.send_code:
            message = await client.async_send_sms_code(args.mobile, SMS_TYPE_VERIFY)
            print(f"短信验证码: {message}")
            if not args.sms_code:
                return 0

        if not (args.password and args.sms_code):
            print("登录需要 --password 与 --sms-code（或先用 --send-code 获取）", file=sys.stderr)
            return 2

        await client.async_login(args.mobile, args.password, args.sms_code)
        print(f"token: {client.token[:8]}…" if client.token else "token: <none>")

        accounts = await client.async_get_accounts()
        print(f"\n发现 {len(accounts)} 个户号：")
        for account in accounts:
            print(
                f"  {account.meter_number}  {account.name}  {account.address}\n"
                f"    欠费={account.arrears}  本期账单={account.current_bill}  余额={account.balance}"
            )

        for account in accounts[: args.limit]:
            try:
                detail = await client.async_get_meter_detail(
                    account.meter_number, account.name
                )
            except ZSWaterError as err:
                print(f"  {account.meter_number} 抄表信息读取失败: {err}")
                continue
            if detail is None:
                continue
            print(
                f"\n{account.meter_number} 抄表：\n"
                f"  上期 {detail.last_reading} @ {detail.last_read_date}\n"
                f"  本期 {detail.current_reading} @ {detail.current_read_date}"
            )
            history = await client.async_get_readings(account.meter_number, days=180)
            for record in history[:5]:
                print(
                    f"    {record.cost_date}  行至 {record.current_read}  "
                    f"水量 {record.consumed_volume}  水费 {record.water_fee}  "
                    f"{record.pay_status or ''}"
                )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="中山公用水务 client demo")
    parser.add_argument("--mobile", required=True, help="登录手机号")
    parser.add_argument("--password", default="", help="登录密码")
    parser.add_argument("--sms-code", default="", help="收到的短信验证码")
    parser.add_argument(
        "--send-code", action="store_true", help="先请求发送短信验证码"
    )
    parser.add_argument("--limit", type=int, default=1, help="打印几个户号的明细")
    return asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
