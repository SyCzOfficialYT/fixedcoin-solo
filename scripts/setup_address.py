#!/usr/bin/env python3
"""FixedCoin: ensure the mining wallet exists/is loaded and preserve the configured payout address."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import requests
import yaml
from requests.auth import HTTPBasicAuth

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "config.yaml"
PLACEHOLDER_RE = re.compile(r"CHANGE|xxxxxxxx|GETNEWADDRESS", re.I)


def load_cfg():
    if not CONFIG_PATH.exists():
        print(f"FEHLER: {CONFIG_PATH} fehlt")
        sys.exit(1)
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f) or {}


def save_payout(addr: str, cfg: dict):
    cfg.setdefault("pool", {})["payout_address"] = addr
    with open(CONFIG_PATH, "w") as f:
        yaml.safe_dump(cfg, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    print(f"config.yaml aktualisiert: payout_address = {addr}")


def rpc(cfg, method, params=None):
    r = cfg["rpc"]
    try:
        resp = requests.post(
            f"http://{r['host']}:{r['port']}",
            json={"jsonrpc": "1.0", "id": "setup", "method": method, "params": params or []},
            auth=HTTPBasicAuth(r["user"], r["password"]),
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("error"):
            return None, data["error"]
        return data.get("result"), None
    except Exception as e:
        return None, str(e)


def ensure_wallet_rpc(cfg):
    """Make sure the named mining wallet is actually loaded before address checks."""
    wallets, err = rpc(cfg, "listwallets")
    if wallets is None:
        print(f"Wallet list unavailable: {err}")
        return False
    wallets = list(wallets or [])
    if "mining" in wallets:
        return True

    result, load_err = rpc(cfg, "loadwallet", ["mining"])
    if result is not None:
        print("Mining wallet loaded.")
        return True

    result, create_err = rpc(cfg, "createwallet", ["mining"])
    if result is not None:
        print("Mining wallet created and loaded.")
        return True

    print(f"WARNING: could not load/create mining wallet: {load_err or create_err}")
    return False


def cli_getnewaddress():
    try:
        out = subprocess.check_output(
            ["fixedcoin-cli", "getnewaddress"],
            stderr=subprocess.STDOUT,
            text=True,
            timeout=60,
        )
        addr = out.strip().splitlines()[-1].strip()
        return addr if addr.startswith("fix1") else None
    except Exception:
        return None


def validate(cfg, addr: str):
    if not addr or not addr.startswith("fix1"):
        return False, "Adresse muss mit fix1 beginnen (FixedCoin Bech32)"
    if PLACEHOLDER_RE.search(addr):
        return False, "Platzhalter-Adresse"
    info, err = rpc(cfg, "validateaddress", [addr])
    if err:
        return False, f"validateaddress fehlgeschlagen: {err}"
    if not info or not info.get("isvalid", False):
        return False, f"Node meldet ungültig: {info}"
    return True, "valid"


def main():
    cfg = load_cfg()

    # IMPORTANT: wallet loading is independent from payout-address validation.
    # A valid address must never cause wallet initialization to be skipped.
    ensure_wallet_rpc(cfg)

    current = (cfg.get("pool") or {}).get("payout_address") or ""
    ok, msg = validate(cfg, current)
    if ok and not PLACEHOLDER_RE.search(current):
        print(f"Holding-Adresse bereits gesetzt und gültig: {current}")
        print(f"  Status: {msg}")
        return 0

    print(f"Aktuelle Adresse unbrauchbar ({current!r}): {msg}")
    print("Erzeuge neue Adresse…")

    addr = cli_getnewaddress()
    if not addr:
        result, err = rpc(cfg, "getnewaddress", [])
        addr = result
    if not addr:
        result, err = rpc(cfg, "getnewaddress", ["holding"])
        addr = result

    if not addr:
        print("FEHLER: konnte keine Adresse erzeugen.")
        print("  Manuell: fixedcoin-cli createwallet mining && fixedcoin-cli getnewaddress")
        return 1

    ok, msg = validate(cfg, addr)
    if not ok:
        print(f"FEHLER: neue Adresse {addr} – {msg}")
        return 1
    save_payout(addr, cfg)
    print(f"Holding-Adresse: {addr}")
    print("  → Dashboard zeigt diese Adresse; Solo-Rewards landen hier.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
