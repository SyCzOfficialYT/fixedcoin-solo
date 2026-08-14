#!/usr/bin/env python3
"""FixedCoin dashboard overlay.

Keeps the FreeCash dashboard data contract, but makes block/reward history
wallet-authoritative so a real coinbase cannot disappear from the UI when
stratum stats rotate/reset.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from monitor import app as base

COINBASE_MATURITY = int(base.COINBASE_MATURITY)

# Never let the browser keep an older dashboard HTML/JSON response around.
@base.app.after_request
def no_dashboard_cache(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


def wallet_coinbase_log(limit: int = 1000):
    """Return our wallet's own coinbase rewards, including immature ones.

    Bitcoin Core reports wallet coinbases as ``immature`` while they have
    <=100 confirmations and ``generate`` once they are mature. We deliberately
    use the wallet as the source of truth instead of stratum.log/stats.json.
    """
    txs, err = base.rpc("listtransactions", ["*", limit, 0, True])
    if not isinstance(txs, list):
        return [], err

    payout = str(base.HOLDING or "").strip()
    rows = {}

    for tx in txs:
        if not isinstance(tx, dict):
            continue
        category = str(tx.get("category") or "").lower()
        generated = tx.get("generated")
        if category not in {"immature", "generate"} and generated is not True:
            continue
        if category == "orphan":
            continue

        address = str(tx.get("address") or "").strip()
        if payout and address != payout:
            continue

        try:
            height = int(tx.get("blockheight"))
            amount = float(tx.get("amount") or 0)
        except (TypeError, ValueError):
            continue
        if height <= 0 or amount <= 0:
            continue

        txid = str(tx.get("txid") or "")
        blockhash = str(tx.get("blockhash") or "")
        key = txid or f"{height}:{blockhash}"
        row = rows.setdefault(
            key,
            {
                "ts": time.strftime(
                    "%Y-%m-%d %H:%M:%S",
                    time.gmtime(tx.get("blocktime") or tx.get("time") or time.time()),
                ),
                "height": height,
                "hash": blockhash[:16] if blockhash else "–",
                "txid": txid,
                "reward": 0.0,
                "address": payout or address,
                "mature_at_height": height + COINBASE_MATURITY,
                "confirmations": int(tx.get("confirmations") or 0),
                "category": category,
            },
        )
        row["reward"] += amount
        row["confirmations"] = max(row["confirmations"], int(tx.get("confirmations") or 0))
        if category == "generate":
            row["category"] = "generate"

    return sorted(rows.values(), key=lambda x: (x["height"], x["txid"]), reverse=True), None


_original_build_payload = base.build_payload


def build_payload():
    payload = _original_build_payload()
    wallet_blocks, wallet_error = wallet_coinbase_log()

    if wallet_error is None:
        payload["blocks_log"] = base.maturity_info(
            payload.get("height", 0), wallet_blocks
        )[:1000]
        payload["blocks_found"] = len(wallet_blocks)
        payload["wallet_blocks_ok"] = True
        payload["wallet_blocks_error"] = None
        payload["rewards_fmt"] = f"{sum(float(x.get('reward') or 0) for x in wallet_blocks):.8f}"
    else:
        payload["wallet_blocks_ok"] = False
        payload["wallet_blocks_error"] = wallet_error

    payload["wallet_authoritative"] = wallet_error is None
    return payload


# Flask handlers in monitor.app resolve build_payload through that module's globals.
base.build_payload = build_payload


if __name__ == "__main__":
    mon = base.CFG.get("monitor") or {}
    base.app.run(
        host=mon.get("host", "0.0.0.0"),
        port=int(mon.get("port", 5050)),
        debug=False,
    )
