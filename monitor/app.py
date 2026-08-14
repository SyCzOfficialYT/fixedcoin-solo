#!/usr/bin/env python3
"""FixedCoin Solo Dashboard – resilient FCH-style SOLO dashboard."""
from flask import Flask, render_template, jsonify
import yaml, json, requests, time, os
from requests.auth import HTTPBasicAuth
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "config.yaml"
EVENTS_PATH = Path(os.environ.get("EVENTS_PATH", str(ROOT / "data" / "events.jsonl")))
STRATUM_LOG = Path(os.environ.get("STRATUM_LOG", str(ROOT / "data" / "stratum.log")))
STATS_PATH = Path(os.environ.get("STATS_PATH", str(ROOT / "data" / "stats.json")))
COINBASE_MATURITY = int(os.environ.get("COINBASE_MATURITY", "100"))
TARGET_BLOCK_SEC = int(os.environ.get("TARGET_BLOCK_SEC", "600"))
# Dashboard requests must never wait for the full node/RPC timeout.  The
# stratum/node may be syncing or temporarily unavailable; the UI still has
# useful local stats and must remain responsive in that state.
DASH_RPC_TIMEOUT = float(os.environ.get("DASH_RPC_TIMEOUT", "3"))

app = Flask(__name__, template_folder="templates")

def load_cfg():
    if CONFIG_PATH.exists():
        return yaml.safe_load(CONFIG_PATH.read_text()) or {}
    return {}

CFG = load_cfg()
RPC = CFG.get("rpc") or {}
RPC_HOST = RPC.get("host", "127.0.0.1")
RPC_PORT = int(RPC.get("port", 24761))
RPC_USER = RPC.get("user", "fixrpc")
RPC_PASS = RPC.get("password", "")
POOL = CFG.get("pool") or {}
HOLDING = POOL.get("payout_address") or ""

def rpc(method, params=None, timeout=None):
    """Best-effort dashboard RPC: failures return immediately and never 500."""
    try:
        r = requests.post(
            f"http://{RPC_HOST}:{RPC_PORT}",
            json={"jsonrpc": "1.0", "id": "dash", "method": method, "params": params or []},
            auth=HTTPBasicAuth(RPC_USER, RPC_PASS),
            timeout=DASH_RPC_TIMEOUT if timeout is None else timeout,
        )
        r.raise_for_status()
        d = r.json()
        if d.get("error"):
            return None, d["error"]
        return d.get("result"), None
    except Exception as e:
        return None, str(e)

def load_stats():
    try:
        if STATS_PATH.exists():
            return json.loads(STATS_PATH.read_text())
    except Exception:
        pass
    return {}

def read_tail_lines(path, limit=120):
    try:
        path = Path(path)
        if not path.exists():
            return []
        return path.read_text(errors="replace").splitlines()[-limit:]
    except Exception:
        return []

def load_events(limit=120):
    out = []
    for raw in read_tail_lines(EVENTS_PATH, limit):
        raw = raw.strip()
        if not raw:
            continue
        try:
            out.append(json.loads(raw))
        except Exception:
            out.append({"ts": "", "level": "INFO", "msg": raw})
    if len(out) < 5:
        for raw in read_tail_lines(STRATUM_LOG, 80):
            if "ACCEPT" in raw or "BLOCK" in raw or "ERROR" in raw:
                out.append({
                    "ts": raw[:19] if len(raw) > 19 else "",
                    "level": "OK" if "ACCEPT" in raw else "INFO",
                    "msg": raw[20:].strip() if len(raw) > 20 else raw,
                })
    return out[-limit:]

def fmt_diff(v):
    try:
        v = float(v or 0)
    except Exception:
        return "–"
    if v <= 0:
        return "0"
    if v >= 1e12:
        return f"{v/1e12:.2f} T"
    if v >= 1e9:
        return f"{v/1e9:.2f} G"
    if v >= 1e6:
        return f"{v/1e6:.2f} M"
    if v >= 1e3:
        return f"{v/1e3:.2f} k"
    return f"{v:.2f}"

def fmt_hashrate(hps):
    try:
        hps = float(hps or 0)
    except Exception:
        return "–"
    if hps <= 0:
        return "–"
    if hps >= 1e18:
        return f"{hps/1e18:.2f} EH/s"
    if hps >= 1e15:
        return f"{hps/1e15:.2f} PH/s"
    if hps >= 1e12:
        return f"{hps/1e12:.2f} TH/s"
    if hps >= 1e9:
        return f"{hps/1e9:.2f} GH/s"
    if hps >= 1e6:
        return f"{hps/1e6:.2f} MH/s"
    if hps >= 1e3:
        return f"{hps/1e3:.2f} kH/s"
    return f"{hps:.0f} H/s"

def fmt_duration(sec):
    try:
        sec = int(sec)
    except Exception:
        return "–"
    if sec < 0:
        sec = 0
    m, s = divmod(sec, 60)
    h, m = divmod(m, 60)
    d, h = divmod(h, 24)
    if d:
        return f"{d}d {h}h"
    if h:
        return f"{h}h {m}m"
    return f"{m}m {s:02d}s"

def _parse_ts(s):
    if not s:
        return None
    try:
        return datetime.strptime(str(s)[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except Exception:
        return None

def maturity_info(height, blocks_log):
    mat = []
    for b in blocks_log or []:
        try:
            bh = int(b.get("height") or 0)
        except Exception:
            continue
        if not bh:
            continue
        mature_at = int(b.get("mature_at_height") or (bh + COINBASE_MATURITY))
        confs = min(COINBASE_MATURITY, max(0, height - bh))
        remaining = max(0, mature_at - height)
        mat.append({
            **b,
            "confs": confs,
            "remaining": remaining,
            "mature": remaining <= 0,
            "mature_at_height": mature_at,
        })
    return mat

def wallet_balances():
    for method in ("getbalances", "getwalletinfo"):
        res, _ = rpc(method)
        if not res:
            continue
        if method == "getbalances":
            mine = res.get("mine") or {}
            return {
                "confirmed": float(mine.get("trusted") or 0),
                "unconfirmed": float(mine.get("untrusted_pending") or 0) + float(mine.get("immature") or 0),
            }
        return {
            "confirmed": float(res.get("balance") or 0),
            "unconfirmed": float(res.get("unconfirmed_balance") or 0) + float(res.get("immature_balance") or 0),
        }
    return {"confirmed": 0.0, "unconfirmed": 0.0}

def resolve_pool_diff(stats):
    """Pool/share difficulty the miner is working at (password d=… / VarDiff)."""
    for key in ("last_share_diff", "share_diff", "pool_difficulty", "current_diff"):
        try:
            v = float(stats.get(key) or 0)
            if v > 0:
                return v
        except Exception:
            pass
    workers = stats.get("workers") or {}
    for w in workers.values() if isinstance(workers, dict) else []:
        if not isinstance(w, dict):
            continue
        for key in ("diff", "difficulty", "share_diff", "pool_diff"):
            try:
                v = float(w.get(key) or 0)
                if v > 0:
                    return v
            except Exception:
                pass
    recent = stats.get("recent_shares") or []
    for s in reversed(recent):
        if not isinstance(s, dict):
            continue
        for key in ("pool_diff", "diff", "difficulty"):
            try:
                v = float(s.get(key) or 0)
                if v > 0:
                    return v
            except Exception:
                pass
    try:
        return float((POOL.get("start_difficulty") or 0))
    except Exception:
        return 0.0

def estimate_hashrate(stats, pool_diff):
    """H = sum(pool_diff per share) * 2^32 / seconds — never use lucky share work."""
    recent = list(stats.get("recent_shares") or [])
    if not recent:
        return 0.0
    times = []
    credited = 0.0
    for s in recent:
        if not isinstance(s, dict):
            continue
        try:
            pd = float(s.get("pool_diff") or s.get("diff") or pool_diff or 0)
        except Exception:
            pd = float(pool_diff or 0)
        if pd > 0:
            credited += pd
        ts = _parse_ts(s.get("ts") or s.get("time") or "")
        if ts:
            times.append(ts)
    if credited <= 0:
        return 0.0
    if len(times) >= 2:
        span = (max(times) - min(times)).total_seconds()
        if span < 1:
            span = 1.0
        span += 0.5 * span / max(len(times) - 1, 1)
        return credited * (2 ** 32) / span
    return credited * (2 ** 32) / max(5.0 * len(recent), 5.0)

def build_payload():
    """Build a usable payload even when fixedcoind RPC is unavailable."""
    stats = load_stats()
    info, _ = rpc("getblockchaininfo")
    net, _ = rpc("getnetworkinfo")
    tip = info or {}
    height = int(tip.get("blocks") or stats.get("round_height") or 0)
    headers = int(tip.get("headers") or height)
    difficulty = float(tip.get("difficulty") or stats.get("network_diff") or 0)
    connections = int((net or {}).get("connections") or 0)
    synced = bool(info) and (not tip.get("initialblockdownload", True)) and height >= max(headers - 1, 0)

    shares_ok = int(stats.get("shares_ok") or 0)
    shares_bad = int(stats.get("shares_bad") or 0)
    total = shares_ok + shares_bad
    reject_pct = (100.0 * shares_bad / total) if total else 0.0
    best = float(stats.get("best_share_diff") or stats.get("round_best") or 0)
    last_work = float(stats.get("last_share_work") or 0)
    share_diff = resolve_pool_diff(stats)
    net_d = float(stats.get("network_diff") or difficulty or 1)
    effort = float(stats.get("round_effort_pct") or 0)
    if not effort and net_d and stats.get("round_work"):
        effort = 100.0 * float(stats["round_work"]) / net_d
    best_pct = (100.0 * best / net_d) if net_d and best else 0.0
    last_pct = (100.0 * last_work / net_d) if net_d and last_work else 0.0
    eta = (net_d / max(last_work, 1e-12) * TARGET_BLOCK_SEC) if last_work and net_d else None

    hr = estimate_hashrate(stats, share_diff)
    wbal = wallet_balances()
    holding = HOLDING or stats.get("payout") or ""
    addr_ok = bool(holding) and not str(holding).startswith("fix1CHANGE")
    addr_msg = "OK" if addr_ok else "set pool.payout_address"

    mat = maturity_info(height, stats.get("blocks_log") or [])
    found_set = {int(b.get("height") or 0) for b in (stats.get("blocks_log") or []) if b.get("height")}
    round_height = int(stats.get("round_height") or height)
    round_started = stats.get("round_started_at") or stats.get("tip_changed_at")

    return {
        "synced": synced,
        "height": height,
        "headers": headers,
        "difficulty": difficulty,
        "difficulty_fmt": fmt_diff(net_d),
        "hashrate_fmt": fmt_hashrate(hr),
        "confirmed": wbal["confirmed"],
        "unconfirmed": wbal["unconfirmed"],
        "confirmed_fmt": f"{wbal['confirmed']:.8f}",
        "unconfirmed_fmt": f"{wbal['unconfirmed']:.8f}",
        "blocks_found": stats.get("blocks_found") or 0,
        "rewards": float(stats.get("block_rewards_total") or 0),
        "rewards_fmt": f"{float(stats.get('block_rewards_total') or 0):.8f}",
        "effort_pct": round(effort, 3),
        "best_pct": round(best_pct, 4),
        "last_pct": round(last_pct, 4),
        "eta_fmt": fmt_duration(eta) if eta else "–",
        "best_share_fmt": fmt_diff(best),
        "last_share_work_fmt": fmt_diff(last_work),
        "shares_ok": shares_ok,
        "shares_bad": shares_bad,
        "reject_pct": round(reject_pct, 1),
        "share_diff_fmt": fmt_diff(share_diff),
        "last_share_time": stats.get("last_share_time"),
        "last_share_hash": stats.get("last_share_hash"),
        "payout": holding,
        "addr_ok": addr_ok,
        "addr_msg": addr_msg,
        "workers": stats.get("workers") or {},
        "started_at": stats.get("started_at"),
        "connections": connections,
        "rpc_host": RPC_HOST,
        "rpc_port": RPC_PORT,
        "rpc_ok": bool(info),
        "recent_shares": list(reversed(stats.get("recent_shares") or []))[:25],
        "blocks_log": list(reversed(mat))[:1000],
        "maturity_blocks": COINBASE_MATURITY,
        "round_height": round_height,
        "round_shares": stats.get("round_shares") or 0,
        "round_work": stats.get("round_work") or 0,
        "round_started_at": round_started,
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "height_strip": [
            {
                "h": h,
                "short": str(h)[-3:].zfill(3) if h >= 100 else str(h),
                "found": h in found_set,
                "current": h == height,
            }
            for h in range(max(0, height - 11), height + 1)
        ],
        "network_diff": net_d,
        "tip_changed_at": stats.get("tip_changed_at") or round_started,
        "target_block_sec": TARGET_BLOCK_SEC,
    }

@app.route("/")
def index():
    return render_template("dashboard.html", **build_payload())

@app.route("/api/status")
def api_status():
    return jsonify(build_payload())

@app.route("/api/health")
def api_health():
    return jsonify({"ok": True, "rpc_ok": bool(rpc("getblockchaininfo")[0]), "ts": time.strftime("%Y-%m-%d %H:%M:%S")})

@app.route("/api/logs")
def api_logs():
    stats = load_stats()
    # Do not make the log endpoint depend on RPC. Local events/stats are enough
    # for the terminal panel and remain available during node sync/restarts.
    return jsonify({
        "events": load_events(120),
        "snapshot": {
            "height": stats.get("round_height"),
            "shares_ok": stats.get("shares_ok", 0),
            "shares_bad": stats.get("shares_bad", 0),
            "blocks_found": stats.get("blocks_found", 0),
            "round_effort_pct": stats.get("round_effort_pct", 0),
            "round_shares": stats.get("round_shares", 0),
            "best_share_diff": stats.get("best_share_diff", 0),
            "last_share_work": stats.get("last_share_work"),
            "last_share_diff": stats.get("last_share_diff"),
        },
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
    })

if __name__ == "__main__":
    mon = CFG.get("monitor") or {}
    app.run(host=mon.get("host", "0.0.0.0"), port=int(mon.get("port", 5050)), debug=False)
