"""Standalone demo for :mod:`zswater_client` — no Home Assistant required.

Run it with a real account to check whether the portal contract still holds
after a portal update::

    python custom_components/zswater/zswater_client_demo.py \\
        --mobile 13800000000 --password 'secret' --captcha 1234 --timestamp 1700000000000

The graphic captcha must be fetched first; ``--captcha-image out.png`` saves it
so you can read the four digits and pass them back via ``--captcha``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time

import aiohttp

from zswater_client import ZSWaterClient


async def _async_main(args: argparse.Namespace) -> int:
    async with aiohttp.ClientSession() as session:
        client = ZSWaterClient(session, timeout=30)

        if args.captcha_image:
            timestamp = args.timestamp or int(time.time() * 1000)
            image = await client.async_get_captcha(timestamp)
            with open(args.captcha_image, "wb") as handle:
                handle.write(image)
            print(f"captcha saved to {args.captcha_image} (timestamp={timestamp})")
            if not args.captcha:
                return 0

        if not args.captcha or not args.timestamp:
            print("login needs --captcha and --timestamp", file=sys.stderr)
            return 2

        data = await client.async_login_with_password(
            args.mobile, args.password, args.captcha, args.timestamp
        )
        print(f"logged in, token={client.token[:8]}..." if client.token else "logged in")
        print(json.dumps(data, ensure_ascii=False, indent=2)[:800])

        accounts = await client.async_get_accounts()
        print(f"\n{len(accounts)} 个户号:")
        for account in accounts:
            print(
                f"  {account.meter_number}  {account.name}  {account.address}\n"
                f"    欠费={account.arrears}  余额={account.balance}  本期账单={account.current_bill}"
            )

        for account in accounts:
            detail = await client.async_get_meter_detail(
                account.meter_number, account.name
            )
            print(
                f"\n{account.meter_number} 抄表: "
                f"上期={detail.last_reading} ({detail.last_read_date})  "
                f"本期={detail.current_reading} ({detail.current_read_date})"
                if detail
                else f"\n{account.meter_number} 抄表数据不可用"
            )
            readings = await client.async_get_readings(account.meter_number, days=120)
            for reading in readings[:3]:
                print(
                    f"    {reading.cost_date}  {reading.last_read} -> {reading.current_read}"
                    f"  {reading.consumed_volume}m³  ¥{reading.water_fee}"
                    f"  违约金¥{reading.penalty}  {reading.pay_status}"
                )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Zhongshan Water client demo")
    parser.add_argument("--mobile", required=True, help="登录手机号")
    parser.add_argument("--password", default="", help="登录密码")
    parser.add_argument("--captcha", default="", help="图形验证码")
    parser.add_argument("--timestamp", default="", help="验证码对应的毫秒时间戳")
    parser.add_argument("--captcha-image", default="", help="把验证码图片保存到此路径")
    args = parser.parse_args()
    return asyncio.run(_async_main(args))


if __name__ == "__main__":
    raise SystemExit(main())
