#!/usr/bin/env python3
"""
FixedCoin Solo Dashboard – Mining-Dutch inspired layout (same as FCH node dashboard).
Queries fixedcoind via JSON-RPC and presents a clean SOLO-focused UI.
Also merges stratum stats.json when present.
"""

import os
import json
time = __import__("time")
from datetime import datetime, timezone
from pathlib import Path

import requests
from flask import Flask, render_template, jsonify
from requests.auth import HTTPBasicAuth

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

app = Flask(__name__, template_folder="templates")
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-change-me")

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "config.yaml"
STATS_PATH = Path(os.environ.get("STATS_PATH", str(ROOT / "data" / "stats.json")))

# Prefer config.yaml (auto-written by entrypoint), then env
def _cfg():
    try:
        import yaml
        if CONFIG_PATH.exists():
            return yaml.safe_load(CONFIG_PATH.read_text()) or {}
    except Exception:
        pass
    return {}

cfg = _cfg()
rpc_c = cfg.get("rpc") or {}
RPC_HOST = os.getenv("RPC_HOST", rpc_c.get("host", "127.0.0.1"))
RPC_PORT = int(os.getenv("RPC_PORT", rpc_c.get("port", 24761)))
RPC_USER = os.getenv("RPC_USER", rpc_c.get("user", "fixrpc"))
RPC_PASSWORD = os.getenv("RPC_PASSWORD", rpc_c.get("password", ""))
FIX_ADDRESS = os.getenv(
    "FIX_ADDRESS",
    (cfg.get("pool") or {}).get("payout_address", ""),
)


def rpc(method: str, params=None):
    payload = {
        "jsonrpc": "1.0",
        "id": "dashboard",
        "method": method,
        "params": params or [],
    }
    try:
        r = requests.post(
            f"http://{RPC_HOST}:{RPC_PORT}",
            json=payload,
            auth=HTTPBasicAuth(RPC_USER, RPC_PASSWORD),
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        if data.get("error"):
            return None, data["error"]
        return data.get("result"), None
    except Exception as e:
        return None, str(e)


def load_stratum_stats():
    try:
        if STATS_PATH.exists():
            return json.loads(STATS_PATH.read_text())
    except Exception:
        pass
    return {}


def get_node_stats():
    info, err = rpc("getblockchaininfo")
    if err or not info:
        return {"error": err or "RPC failed"}

    mining_info, _ = rpc("getmininginfo")
    network_info, _ = rpc("getnetworkinfo")
    mempool, _ = rpc("getmempoolinfo")

    nethash = None
    try:
        nh, _ = rpc("getnetworkhashps", [120])
        nethash = nh
    except Exception:
        pass

    st = load_stratum_stats()
    return {
        "height": info.get("blocks"),
        "headers": info.get("headers"),
        "difficulty": info.get("difficulty"),
        "chain": info.get("chain"),
        "verification_progress": info.get("verificationprogress"),
        "pruned": info.get("pruned"),
        "nethash": nethash,
        "mining": mining_info or {},
        "connections": (network_info or {}).get("connections"),
        "mempool_size": (mempool or {}).get("size"),
        "mempool_bytes": (mempool or {}).get("bytes"),
        "synced": info.get("blocks") == info.get("headers"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        # stratum extras
        "shares_ok": st.get("shares_ok", 0),
        "shares_bad": st.get("shares_bad", 0),
        "blocks_found": st.get("blocks_found", 0),
        "effort_pct": st.get("round_effort_pct", 0),
        "best_share": st.get("best_share_diff", 0),
        "hashrate_hint": st.get("last_share_diff"),
    }


@app.route("/")
def index():
    stats = get_node_stats()
    addr = FIX_ADDRESS
    try:
        c = _cfg()
        addr = (c.get("pool") or {}).get("payout_address") or addr
    except Exception:
        pass
    return render_template(
        "dashboard.html",
        stats=stats,
        address=addr,
        now=datetime.now(timezone.utc),
    )


@app.route("/api/stats")
def api_stats():
    return jsonify(get_node_stats())


@app.route("/api/status")
def api_status():
    """Alias for older solo UI clients."""
    return jsonify(get_node_stats())


@app.route("/health")
def health():
    stats = get_node_stats()
    if stats.get("error"):
        return jsonify({"status": "error", "detail": stats["error"]}), 503
    return jsonify({"status": "ok", "height": stats.get("height")})


if __name__ == "__main__":
    port = int(os.getenv("FIX_DASH_PORT", (cfg.get("monitor") or {}).get("port", 5050)))
    app.run(host="0.0.0.0", port=port, debug=False)
