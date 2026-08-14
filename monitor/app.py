#!/usr/bin/env python3
"""FixedCoin Solo Dashboard – resilient read-only dashboard."""
from flask import Flask, render_template, jsonify
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
import yaml
from requests.auth import HTTPBasicAuth

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "config.yaml"
EVENTS_PATH = Path(os.environ.get("EVENTS_PATH", str(ROOT / "data" / "events.jsonl")))
STRATUM_LOG = Path(os.environ.get("STRATUM_LOG", str(ROOT / "data" / "stratum.log")))
STATS_PATH = Path(os.environ.get("STATS_PATH", str(ROOT / "data" / "stats.json")))
COINBASE_MATURITY = int(os.environ.get("COINBASE_MATURITY", "100"))
TARGET_BLOCK_SEC = int(os.environ.get("TARGET_BLOCK_SEC", "600"))
DASH_RPC_TIMEOUT = float(os.environ.get("DASH_RPC_TIMEOUT", "3"))

app = Flask(__name__, template_folder="templates")


def load_cfg():
    try:
        return yaml.safe_load(CONFIG_PATH.read_text()) or {}
    except Exception:
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
        if STATS_PATH.exists() and STATS_PATH.stat().st_size:
            value = json.loads(STATS_PATH.read_text())
            return value if isinstance(value, dict) else {}
    except Exception:
        pass
    return {}


def read_tail_lines(path, limit=2000):
    try:
        p = Path(path)
        if not p.exists():
            return []
        return p.read_text(errors="replace").splitlines()[-limit:]
    except Exception:
        return []


def _parse_ts(s):
    if not s:
        return None
    try:
        return datetime.strptime(str(s)[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except Exception:
        return None


def parse_stratum_log():
    """Recover live mining state from stratum.log when stats.json is empty/stale."""
    lines = read_tail_lines(STRATUM_LOG, 5000)
    accepted = []
    rejected = 0
    workers = {}
    current_worker = None
    current_diff = 0.0
    round_height = 0
    round_netdiff = 0.0
    round_work = 0.0
    round_shares = 0
    best_work = 0.0
    last_share = None
    blocks = []

    auth_re = re.compile(r"authorize\s+(\S+)\s+diff=(\d+(?:\.\d+)?)")
    accept_re = re.compile(r"(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d).*?ACCEPT\s+#(\d+)\s+work=([0-9.]+).*?pool=([0-9.]+).*?round=([0-9.]+)%\s+hash=([0-9a-fA-F]+)")
    reject_re = re.compile(r"REJECT\s+low difficulty\s+need=([0-9.]+)\s+work=([0-9.]+)\s+hash=([0-9a-fA-F]+)")
    round_re = re.compile(r"NEW ROUND\s+height=(\d+)\s+netdiff=([0-9.]+)")
    block_re = re.compile(r"(?:BLOCK FOUND|BLOCKFOUND|FOUND BLOCK).*?(?:height[= ](\d+))?.*?(?:hash[= ]([0-9a-fA-F]{16,64}))?.*?(?:reward[= ]([0-9.]+))?", re.I)

    for line in lines:
        m = auth_re.search(line)
        if m:
            current_worker = m.group(1)
            current_diff = float(m.group(2))
            w = workers.setdefault(current_worker, {"ok": 0, "bad": 0, "diff": current_diff})
            w["diff"] = current_diff
            continue
        m = round_re.search(line)
        if m:
            round_height = int(m.group(1))
            round_netdiff = float(m.group(2))
            round_work = 0.0
            round_shares = 0
            best_work = 0.0
            continue
        m = accept_re.search(line)
        if m:
            ts, num, work, pool_diff, round_pct, h = m.groups()
            work = float(work)
            pool_diff = float(pool_diff)
            accepted.append({
                "ts": ts,
                "num": int(num),
                "work": work,
                "pool_diff": pool_diff,
                "net_pct": float(work / round_netdiff * 100.0) if round_netdiff else 0.0,
                "round_pct": float(round_pct),
                "hash": h,
                "height": round_height or None,
            })
            round_work += work
            round_shares += 1
            best_work = max(best_work, work)
            last_share = accepted[-1]
            if current_worker:
                workers.setdefault(current_worker, {"ok": 0, "bad": 0, "diff": current_diff})["ok"] += 1
            continue
        m = reject_re.search(line)
        if m:
            rejected += 1
            if current_worker:
                workers.setdefault(current_worker, {"ok": 0, "bad": 0, "diff": current_diff})["bad"] += 1
            continue
        m = block_re.search(line)
        if m:
            bh, bhash, reward = m.groups()
            blocks.append({
                "height": int(bh) if bh else round_height,
                "hash": bhash or "–",
                "reward": float(reward) if reward else 0.0,
            })

    return {
        "shares_ok": len(accepted),
        "shares_bad": rejected,
        "recent_shares": accepted[-100:],
        "workers": workers,
        "round_height": round_height,
        "network_diff": round_netdiff,
        "round_work": round_work,
        "round_shares": round_shares,
        "best_share_diff": best_work,
        "last_share_work": last_share.get("work", 0) if last_share else 0,
        "last_share_time": last_share.get("ts") if last_share else None,
        "last_share_hash": last_share.get("hash") if last_share else None,
        "blocks_log": blocks[-1000:],
        "blocks_found": len(blocks),
    }


def merge_runtime_stats(stats, logstats):
    """Prefer persisted state, but transparently recover missing values from the log."""
    out = dict(stats)
    if not out.get("recent_shares") and logstats["recent_shares"]:
        out["recent_shares"] = logstats["recent_shares"]
    if int(out.get("shares_ok") or 0) == 0 and logstats["shares_ok"]:
        out["shares_ok"] = logstats["shares_ok"]
    if int(out.get("shares_bad") or 0) == 0 and logstats["shares_bad"]:
        out["shares_bad"] = logstats["shares_bad"]
    if not out.get("workers") and logstats["workers"]:
        out["workers"] = logstats["workers"]
    for key in ("round_height", "network_diff", "round_work", "round_shares", "best_share_diff", "last_share_work", "last_share_time", "last_share_hash"):
        if not out.get(key) and logstats.get(key):
            out[key] = logstats[key]
    if not out.get("blocks_log") and logstats["blocks_log"]:
        out["blocks_log"] = logstats["blocks_log"]
    if int(out.get("blocks_found") or 0) == 0 and logstats["blocks_found"]:
        out["blocks_found"] = logstats["blocks_found"]
    return out


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
        for raw in read_tail_lines(STRATUM_LOG, 200):
            if any(x in raw for x in ("ACCEPT", "BLOCK", "ERROR", "REJECT", "authorize", "NEW ROUND")):
                out.append({
                    "ts": raw[:19] if len(raw) > 19 else "",
                    "level": "OK" if "ACCEPT" in raw or "BLOCK" in raw else ("WARN" if "REJECT" in raw else "INFO"),
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
    for unit, scale in (("EH/s", 1e18), ("PH/s", 1e15), ("TH/s", 1e12), ("GH/s", 1e9), ("MH/s", 1e6), ("kH/s", 1e3)):
        if hps >= scale:
            return f"{hps/scale:.2f} {unit}"
    return f"{hps:.0f} H/s"


def fmt_duration(sec):
    try:
        sec = max(0, int(sec))
    except Exception:
        return "–"
    m, s = divmod(sec, 60)
    h, m = divmod(m, 60)
    d, h = divmod(h, 24)
    if d:
        return f"{d}d {h}h"
    if h:
        return f"{h}h {m}m"
    return f"{m}m {s:02d}s"


def maturity_info(height, blocks_log):
    out = []
    for b in blocks_log or []:
        try:
            bh = int(b.get("height") or 0)
        except Exception:
            continue
        if not bh:
            continue
        mature_at = int(b.get("mature_at_height") or bh + COINBASE_MATURITY)
        remaining = max(0, mature_at - height)
        out.append({
            **b,
            "confs": min(COINBASE_MATURITY, max(0, height - bh)),
            "remaining": remaining,
            "left": remaining,
            "mature": remaining == 0,
            "spendable": remaining == 0,
            "mature_at_height": mature_at,
        })
    return out


def resolve_pool_diff(stats):
    for key in ("last_share_diff", "share_diff", "pool_difficulty", "current_diff"):
        try:
            v = float(stats.get(key) or 0)
            if v > 0:
                return v
        except Exception:
            pass
    for w in (stats.get("workers") or {}).values() if isinstance(stats.get("workers"), dict) else []:
        for key in ("diff", "difficulty", "share_diff", "pool_diff"):
            try:
                v = float(w.get(key) or 0)
                if v > 0:
                    return v
            except Exception:
                pass
    for s in reversed(stats.get("recent_shares") or []):
        for key in ("pool_diff", "diff", "difficulty"):
            try:
                v = float(s.get(key) or 0)
                if v > 0:
                    return v
            except Exception:
                pass
    return float(POOL.get("fixed_difficulty") or POOL.get("start_difficulty") or 0)


def estimate_hashrate(stats, pool_diff):
    recent = [s for s in stats.get("recent_shares") or [] if isinstance(s, dict)]
    if not recent:
        return 0.0
    times = []
    credited = 0.0
    for s in recent:
        try:
            credited += float(s.get("pool_diff") or s.get("diff") or pool_diff or 0)
        except Exception:
            pass
        ts = _parse_ts(s.get("ts") or s.get("time") or "")
        if ts:
            times.append(ts)
    if credited <= 0:
        return 0.0
    if len(times) >= 2:
        span = max(1.0, (max(times) - min(times)).total_seconds())
        return credited * (2 ** 32) / span
    return credited * (2 ** 32) / max(5.0, 5.0 * len(recent))


def wallet_balances():
    wallets, wallet_err = rpc("listwallets")
    wallet_loaded = bool(wallets is not None and "mining" in (wallets or []))
    for method in ("getbalances", "getwalletinfo"):
        res, err = rpc(method)
        if not res:
            continue
        if method == "getbalances":
            mine = res.get("mine") or {}
            return {
                "confirmed": float(mine.get("trusted") or 0),
                "unconfirmed": float(mine.get("untrusted_pending") or 0) + float(mine.get("immature") or 0),
                "wallet_loaded": wallet_loaded,
                "wallet_error": wallet_err,
            }
        return {
            "confirmed": float(res.get("balance") or 0),
            "unconfirmed": float(res.get("unconfirmed_balance") or 0) + float(res.get("immature_balance") or 0),
            "wallet_loaded": wallet_loaded,
            "wallet_error": wallet_err,
        }
    return {"confirmed": 0.0, "unconfirmed": 0.0, "wallet_loaded": wallet_loaded, "wallet_error": wallet_err}


def build_payload():
    stats = merge_runtime_stats(load_stats(), parse_stratum_log())
    info, info_err = rpc("getblockchaininfo")
    net, _ = rpc("getnetworkinfo")
    gbt, _ = rpc("getblocktemplate", [{"rules": ["segwit"]}])
    tip = info or {}
    height = int(tip.get("blocks") or stats.get("round_height") or 0)
    headers = int(tip.get("headers") or height)
    difficulty = float(tip.get("difficulty") or stats.get("network_diff") or 0)
    connections = int((net or {}).get("connections") or 0)
    synced = bool(info) and not tip.get("initialblockdownload", True) and height >= max(headers - 1, 0)

    shares_ok = int(stats.get("shares_ok") or 0)
    shares_bad = int(stats.get("shares_bad") or 0)
    total = shares_ok + shares_bad
    reject_pct = 100.0 * shares_bad / total if total else 0.0
    best = float(stats.get("best_share_diff") or stats.get("round_best") or 0)
    last_work = float(stats.get("last_share_work") or 0)
    share_diff = resolve_pool_diff(stats)
    net_d = float(stats.get("network_diff") or difficulty or 1)
    round_work = float(stats.get("round_work") or 0)
    effort = float(stats.get("round_effort_pct") or 0)
    if not effort and net_d and round_work:
        effort = 100.0 * round_work / net_d
    best_pct = 100.0 * best / net_d if net_d and best else 0.0
    last_pct = 100.0 * last_work / net_d if net_d and last_work else 0.0
    eta = net_d / max(last_work, 1e-12) * TARGET_BLOCK_SEC if last_work and net_d else None
    hr = estimate_hashrate(stats, share_diff)
    wbal = wallet_balances()
    holding = HOLDING or stats.get("payout") or ""
    addr_ok = bool(holding) and not str(holding).startswith("fix1CHANGE")

    mat = maturity_info(height, stats.get("blocks_log") or [])
    found_set = {int(b.get("height") or 0) for b in (stats.get("blocks_log") or []) if b.get("height")}
    round_height = int(stats.get("round_height") or height)
    job_height = int((gbt or {}).get("height") or round_height or height)
    job_prevhash = (gbt or {}).get("previousblockhash") or "–"
    job_nbits = (gbt or {}).get("bits") or "–"
    job_ntime = (gbt or {}).get("curtime") or "–"
    job_version = (gbt or {}).get("version") or "–"
    job_id = f"{job_height}:{job_prevhash[:12]}" if job_prevhash != "–" else "–"
    tip_time = int(tip.get("mediantime") or tip.get("time") or time.time())
    tip_age = max(0, int(time.time()) - tip_time)
    network_eta = max(0, TARGET_BLOCK_SEC - tip_age % TARGET_BLOCK_SEC)
    round_started = stats.get("round_started_at") or stats.get("tip_changed_at")

    return {
        "synced": synced, "height": height, "headers": headers,
        "difficulty": difficulty, "network_diff": net_d,
        "difficulty_fmt": fmt_diff(net_d), "hashrate_fmt": fmt_hashrate(hr),
        "confirmed": wbal["confirmed"], "unconfirmed": wbal["unconfirmed"],
        "confirmed_fmt": f"{wbal['confirmed']:.8f}", "unconfirmed_fmt": f"{wbal['unconfirmed']:.8f}",
        "wallet_loaded": wbal.get("wallet_loaded", False), "wallet_error": wbal.get("wallet_error"),
        "blocks_found": int(stats.get("blocks_found") or 0),
        "rewards": float(stats.get("block_rewards_total") or 0),
        "rewards_fmt": f"{float(stats.get('block_rewards_total') or 0):.8f}",
        "effort_pct": round(effort, 3), "best_pct": round(best_pct, 4), "last_pct": round(last_pct, 4),
        "eta_fmt": fmt_duration(eta) if eta else "–", "best_share_fmt": fmt_diff(best), "last_share_work_fmt": fmt_diff(last_work),
        "shares_ok": shares_ok, "shares_bad": shares_bad, "reject_pct": round(reject_pct, 1),
        "share_diff_fmt": fmt_diff(share_diff), "last_share_time": stats.get("last_share_time"), "last_share_hash": stats.get("last_share_hash"),
        "payout": holding, "addr_ok": addr_ok, "addr_msg": "OK" if addr_ok else "set pool.payout_address",
        "workers": stats.get("workers") or {}, "started_at": stats.get("started_at"), "connections": connections,
        "rpc_host": RPC_HOST, "rpc_port": RPC_PORT, "rpc_ok": bool(info), "rpc_error": info_err,
        "recent_shares": list(reversed(stats.get("recent_shares") or []))[:100],
        "blocks_log": list(reversed(mat))[:1000], "maturity_blocks": COINBASE_MATURITY,
        "round_height": round_height, "round_shares": stats.get("round_shares") or 0, "round_work": round_work,
        "round_started_at": round_started, "tip_changed_at": stats.get("tip_changed_at") or round_started,
        "target_block_sec": TARGET_BLOCK_SEC, "tip_age": tip_age, "network_eta": network_eta,
        "job_id": job_id, "job_height": job_height, "job_prevhash": job_prevhash,
        "job_nbits": job_nbits, "job_ntime": job_ntime, "job_version": job_version,
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "height_strip": [
            {"h": h, "short": str(h)[-3:].zfill(3), "found": h in found_set, "current": h == height}
            for h in range(max(0, height - 11), height + 1)
        ],
    }


@app.route("/")
def index():
    return render_template("dashboard.html", **build_payload())


@app.route("/api/status")
def api_status():
    return jsonify(build_payload())


@app.route("/api/health")
def api_health():
    result, _ = rpc("getblockchaininfo")
    return jsonify({"ok": True, "rpc_ok": bool(result), "ts": time.strftime("%Y-%m-%d %H:%M:%S")})


@app.route("/api/logs")
def api_logs():
    stats = merge_runtime_stats(load_stats(), parse_stratum_log())
    return jsonify({
        "events": load_events(160),
        "snapshot": {
            "height": stats.get("round_height"), "shares_ok": stats.get("shares_ok", 0),
            "shares_bad": stats.get("shares_bad", 0), "blocks_found": stats.get("blocks_found", 0),
            "round_effort_pct": stats.get("round_effort_pct", 0), "round_shares": stats.get("round_shares", 0),
            "best_share_diff": stats.get("best_share_diff", 0), "last_share_work": stats.get("last_share_work", 0),
            "last_share_diff": stats.get("last_share_diff", 0),
        },
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
    })


if __name__ == "__main__":
    mon = CFG.get("monitor") or {}
    app.run(host=mon.get("host", "0.0.0.0"), port=int(mon.get("port", 5050)), debug=False)
