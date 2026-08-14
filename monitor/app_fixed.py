#!/usr/bin/env python3
"""FixedCoin dashboard overlay: keep the FCH-style UI, make wallet/coinbase state authoritative."""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from monitor import app as base

COINBASE_MATURITY = int(base.COINBASE_MATURITY)


def wallet_coinbase_log(limit: int = 1000):
    """Rebuild block history from the mining wallet, not from transient stratum stats."""
    txs, err = base.rpc("listtransactions", ["*", limit, 0, True])
    if not isinstance(txs, list):
        return [], err

    payout = base.HOLDING
    rows = {}
    for tx in txs:
        if not isinstance(tx, dict):
            continue
        category = str(tx.get("category") or "").lower()
        if category not in {"immature", "generate"} and not tx.get("generated"):
            continue
        if tx.get("generated") is False:
            continue
        if payout and tx.get("address") and tx.get("address") != payout:
            continue
        height = tx.get("blockheight")
        if height is None:
            continue
        try:
            height = int(height)
            amount = float(tx.get("amount") or 0)
        except (TypeError, ValueError):
            continue
        if height <= 0:
            continue
        txid = str(tx.get("txid") or "")
        blockhash = str(tx.get("blockhash") or "")
        key = txid or f"{height}:{blockhash}"
        rows[key] = {
            "ts": time.strftime(
                "%Y-%m-%d %H:%M:%S",
                time.gmtime(tx.get("blocktime") or tx.get("time") or time.time()),
            ),
            "height": height,
            "hash": blockhash[:16] if blockhash else "–",
            "txid": txid,
            "reward": amount,
            "address": payout,
            "mature_at_height": height + COINBASE_MATURITY,
            "confirmations": int(tx.get("confirmations") or 0),
            "category": category,
        }
    return sorted(rows.values(), key=lambda x: (x["height"], x["txid"]), reverse=True), None


_original_build_payload = base.build_payload


def build_payload():
    payload = _original_build_payload()
    wallet_blocks, wallet_error = wallet_coinbase_log()
    if wallet_blocks:
        # Wallet is the source of truth for an actually accepted coinbase.
        payload["blocks_log"] = base.maturity_info(
            payload.get("height", 0), wallet_blocks
        )[:1000]
        payload["blocks_found"] = len(wallet_blocks)
        payload["wallet_blocks_ok"] = True
        payload["wallet_blocks_error"] = None
        payload["rewards_fmt"] = f"{sum(float(x.get('reward') or 0) for x in wallet_blocks):.8f}"
    else:
        payload["wallet_blocks_ok"] = wallet_error is None
        payload["wallet_blocks_error"] = wallet_error
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
