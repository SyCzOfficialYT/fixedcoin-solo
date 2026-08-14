#!/usr/bin/env python3
"""Regression test for wallet-authoritative FixedCoin coinbase tracking."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from monitor import app_fixed


def main() -> None:
    expected = "fix1qe60s2t5kdr5fugje4zs0djtgf7larsl8jhayq8"
    txs = [
        {
            "category": "immature",
            "generated": True,
            "address": expected,
            "blockheight": 1000,
            "blockhash": "aa" * 32,
            "txid": "11" * 32,
            "amount": 25.0,
            "confirmations": 1,
        },
        {
            "category": "generate",
            "generated": True,
            "address": expected,
            "blockheight": 900,
            "blockhash": "bb" * 32,
            "txid": "22" * 32,
            "amount": 12.5,
            "confirmations": 101,
        },
        {
            "category": "immature",
            "generated": True,
            "address": "fix1not-our-payout",
            "blockheight": 1100,
            "blockhash": "cc" * 32,
            "txid": "33" * 32,
            "amount": 25.0,
        },
    ]

    original = app_fixed.base.rpc
    app_fixed.base.rpc = lambda method, params=None: (txs, None) if method == "listtransactions" else (None, "unused")
    try:
        rows, err = app_fixed.wallet_coinbase_log()
    finally:
        app_fixed.base.rpc = original

    assert err is None
    assert [r["height"] for r in rows] == [1000, 900]
    assert rows[0]["mature_at_height"] == 1100
    assert rows[0]["category"] == "immature"
    assert rows[1]["category"] == "generate"
    assert all(r["address"] == expected for r in rows)

    immature = app_fixed.base.maturity_info(1000, rows)[0]
    assert immature["left"] == 100
    assert immature["spendable"] is False

    mature = app_fixed.base.maturity_info(1100, rows)[0]
    assert mature["left"] == 0
    assert mature["spendable"] is True

    print("PASS: wallet coinbase flow filters payout, shows immature, then becomes spendable at maturity")


if __name__ == "__main__":
    main()
