#!/usr/bin/env python3
"""FixedCoin: ensure the mining wallet is loaded and persist one payout address."""
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
DATADIR = Path(__import__("os").environ.get("FIX_DATADIR", "/data/fixedcoin"))
PAYOUT_FILE = DATADIR / "payout_address"
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
    DATADIR.mkdir(parents=True, exist_ok=True)
    PAYOUT_FILE.write_text(addr + "\n")
    print(f"config.yaml aktualisiert: payout_address = {addr}")
    print(f"Persistente payout_address gespeichert: {PAYOUT_FILE}")


def persist_existing(addr: str):
    DATADIR.mkdir(parents=True, exist_ok=True)
    if PAYOUT_FILE.exists() and PAYOUT_FILE.read_text().strip() == addr:
        return
    PAYOUT_FILE.write_text(addr + "\n")
    print(f"Persistente payout_address gespeichert: {PAYOUT_FILE}")


def rpc(cfg, method, params=None):
    r = cfg["rpc"]
    try:
        resp = requests.post(
            f"http://{r['host']}:{r['port']}",
            json={"jsonrpc": "1.0", "id": "setup", "method": method, "params": params or []},
            auth=HTTPBasicAuth(r["user"], r["password"]),
            timeout=30,
        )
        try:
            data = resp.json()
        except Exception:
            data = None
        if resp.status_code != 200:
            detail = data.get("error") if isinstance(data, dict) else resp.text[:500]
            return None, f"HTTP {resp.status_code}: {detail}"
        if isinstance(data, dict) and data.get("error"):
            return None, data["error"]
        return data.get("result") if isinstance(data, dict) else None, None
    except Exception as e:
        return None, str(e)


def ensure_wallet_rpc(cfg):
    """Load the existing mining wallet; only create it if it truly does not exist."""
    wallets, err = rpc(cfg, "listwallets")
    if wallets is None:
        print(f"Wallet list unavailable: {err}")
        return False
    wallets = list(wallets or [])
    if "mining" in wallets:
        print("Mining wallet already loaded — keeping existing wallet/address.")
        return True

    result, load_err = rpc(cfg, "loadwallet", ["mining"])
    if result is not None:
        print("Existing mining wallet loaded — no new wallet generated.")
        return True

    # A missing wallet is the only normal reason to create it.
    if isinstance(load_err, dict):
        msg = str(load_err.get("message", ""))
        if "not found" not in msg.lower() and "does not exist" not in msg.lower():
            print(f"WARNING: loadwallet failed: {load_err}")
            return False
    elif load_err and "not found" not in str(load_err).lower() and "does not exist" not in str(load_err).lower():
        print(f"WARNING: loadwallet failed: {load_err}")
        return False

    result, create_err = rpc(cfg, "createwallet", ["mining"])
    if result is not None:
        print("Mining wallet created and loaded (first-run only).")
        return True

    print(f"WARNING: could not create mining wallet: {create_err}")
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

    ensure_wallet_rpc(cfg)

    # Persistent payout state wins over the image's example config.
    persistent = PAYOUT_FILE.read_text().strip() if PAYOUT_FILE.exists() else ""
    if persistent:
        current = persistent
        cfg.setdefault("pool", {})["payout_address"] = current
    else:
        current = (cfg.get("pool") or {}).get("payout_address") or ""

    ok, msg = validate(cfg, current)
    if ok and not PLACEHOLDER_RE.search(current):
        save_payout(current, cfg)
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
        print("Manuell: fixedcoin-cli createwallet mining && fixedcoin-cli getnewaddress")
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
