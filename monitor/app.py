#!/usr/bin/env python3
"""FixedCoin Solo Dashboard – exact FCH-style SOLO UI with live FixedCoin data."""
from flask import Flask, render_template, jsonify
import json, os, re, time
from datetime import datetime, timezone
from pathlib import Path
import requests, yaml
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
    try: return yaml.safe_load(CONFIG_PATH.read_text()) or {}
    except Exception: return {}
CFG=load_cfg(); RPC=CFG.get("rpc") or {}; RPC_HOST=RPC.get("host","127.0.0.1"); RPC_PORT=int(RPC.get("port",24761)); RPC_USER=RPC.get("user","fixrpc"); RPC_PASS=RPC.get("password",""); POOL=CFG.get("pool") or {}; HOLDING=POOL.get("payout_address") or ""

def rpc(method, params=None, timeout=None):
    try:
        r=requests.post(f"http://{RPC_HOST}:{RPC_PORT}",json={"jsonrpc":"1.0","id":"dash","method":method,"params":params or []},auth=HTTPBasicAuth(RPC_USER,RPC_PASS),timeout=DASH_RPC_TIMEOUT if timeout is None else timeout); r.raise_for_status(); d=r.json()
        if d.get("error"): return None,d["error"]
        return d.get("result"),None
    except Exception as e: return None,str(e)

def load_stats():
    try:
        if STATS_PATH.exists() and STATS_PATH.stat().st_size:
            d=json.loads(STATS_PATH.read_text()); return d if isinstance(d,dict) else {}
    except Exception: pass
    return {}

def read_tail_lines(path,limit=5000):
    try:
        p=Path(path); return p.read_text(errors="replace").splitlines()[-limit:] if p.exists() else []
    except Exception: return []

def _parse_ts(s):
    try: return datetime.strptime(str(s)[:19],"%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc) if s else None
    except Exception: return None

def parse_stratum_log():
    lines=read_tail_lines(STRATUM_LOG,5000); accepted=[]; rejected=0; workers={}; current_worker=None; current_diff=0.0; round_height=0; round_netdiff=0.0; round_work=0.0; round_shares=0; best_work=0.0; last=None; blocks=[]
    auth_re=re.compile(r"authorize\s+(\S+)\s+diff=(\d+(?:\.\d+)?)",re.I); accept_re=re.compile(r"(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d).*?ACCEPT\s+#(\d+)\s+work=([0-9.]+).*?pool=([0-9.]+).*?round=([0-9.]+)%\s+hash=([0-9a-fA-F]+)",re.I); reject_re=re.compile(r"REJECT\s+low difficulty\s+need=([0-9.]+)\s+work=([0-9.]+)\s+hash=([0-9a-fA-F]+)",re.I); round_re=re.compile(r"NEW ROUND\s+height=(\d+)\s+netdiff=([0-9.]+)",re.I); block_re=re.compile(r"(?:BLOCK FOUND|BLOCKFOUND|FOUND BLOCK).*?(?:height[= ](\d+))?.*?(?:hash[= ]([0-9a-fA-F]{16,64}))?.*?(?:reward[= ]([0-9.]+))?",re.I)
    for line in lines:
        m=auth_re.search(line)
        if m: current_worker=m.group(1); current_diff=float(m.group(2)); workers.setdefault(current_worker,{"ok":0,"bad":0,"diff":current_diff})["diff"]=current_diff; continue
        m=round_re.search(line)
        if m: round_height=int(m.group(1)); round_netdiff=float(m.group(2)); round_work=round_shares=0; best_work=0.0; continue
        m=accept_re.search(line)
        if m:
            ts,num,work,pool_diff,rpct,h=m.groups(); work=float(work); pool_diff=float(pool_diff); last={"ts":ts,"num":int(num),"work":work,"pool_diff":pool_diff,"net_pct":100*work/round_netdiff if round_netdiff else 0,"round_pct":float(rpct),"hash":h,"height":round_height or None}; accepted.append(last); round_work+=work; round_shares+=1; best_work=max(best_work,work)
            if current_worker: workers.setdefault(current_worker,{"ok":0,"bad":0,"diff":current_diff})["ok"]+=1
            continue
        if reject_re.search(line):
            rejected+=1
            if current_worker: workers.setdefault(current_worker,{"ok":0,"bad":0,"diff":current_diff})["bad"]+=1
            continue
        m=block_re.search(line)
        if m:
            bh,bhash,reward=m.groups(); blocks.append({"height":int(bh) if bh else round_height,"hash":bhash or "–","reward":float(reward) if reward else 0.0})
    return {"shares_ok":len(accepted),"shares_bad":rejected,"recent_shares":accepted[-100:],"workers":workers,"round_height":round_height,"network_diff":round_netdiff,"round_work":round_work,"round_shares":round_shares,"best_share_diff":best_work,"last_share_work":last.get("work",0) if last else 0,"last_share_time":last.get("ts") if last else None,"last_share_hash":last.get("hash") if last else None,"blocks_log":blocks[-1000:],"blocks_found":len(blocks)}

def merge_runtime_stats(stats,logstats):
    out=dict(stats)
    for k in ("recent_shares","workers","blocks_log"):
        if not out.get(k) and logstats.get(k): out[k]=logstats[k]
    for k in ("shares_ok","shares_bad","round_height","network_diff","round_work","round_shares","best_share_diff","last_share_work","last_share_time","last_share_hash","blocks_found"):
        if not out.get(k) and logstats.get(k): out[k]=logstats[k]
    return out

def load_events(limit=160):
    out=[]
    try:
        if EVENTS_PATH.exists():
            for raw in EVENTS_PATH.read_text(errors="replace").splitlines()[-limit:]:
                try:
                    e=json.loads(raw)
                    if isinstance(e,dict): out.append(e)
                except Exception:
                    if raw.strip(): out.append({"ts":"","level":"INFO","msg":raw})
    except Exception: pass
    for raw in read_tail_lines(STRATUM_LOG,300):
        if not any(x in raw for x in ("ACCEPT","BLOCK","ERROR","REJECT","authorize","NEW ROUND")): continue
        level="OK" if "ACCEPT" in raw or "BLOCK" in raw else "WARN" if "REJECT" in raw else "INFO"; out.append({"ts":raw[:19],"level":level,"msg":raw[20:].strip() if len(raw)>20 else raw})
    return out[-limit:]

def fmt_diff(v):
    try:v=float(v)
    except Exception:return "0"
    if v>=1e9:return f"{v/1e9:.2f} G"
    if v>=1e6:return f"{v/1e6:.2f} M"
    if v>=1e3:return f"{v/1e3:.2f} K"
    return f"{v:.0f}"

def fmt_hashrate(v):
    try:v=float(v)
    except Exception:return "–"
    for scale,unit in ((1e18,"EH/s"),(1e15,"PH/s"),(1e12,"TH/s"),(1e9,"GH/s"),(1e6,"MH/s"),(1e3,"KH/s")):
        if v>=scale:return f"{v/scale:.2f} {unit}"
    return f"{v:.2f} H/s" if v>0 else "–"

def fmt_duration(s):
    if s is None:return "–"
    s=max(0,int(s))
    if s<60:return f"{s}s"
    if s<3600:return f"{s//60}m {s%60}s"
    return f"{s//3600}h {(s%3600)//60}m"

def maturity_info(height,items):
    out=[]
    for b in items or []:
        try:bh=int(b.get("height") or 0)
        except Exception:continue
        if not bh:continue
        mature_at=int(b.get("mature_at_height") or bh+COINBASE_MATURITY); left=max(0,mature_at-height); out.append({**b,"confs":min(COINBASE_MATURITY,max(0,height-bh)),"remaining":left,"left":left,"mature":left==0,"spendable":left==0,"mature_at_height":mature_at})
    return out

def resolve_pool_diff(s):
    for k in ("last_share_diff","share_diff","pool_difficulty","current_diff"):
        try:v=float(s.get(k) or 0)
        except Exception:continue
        if v>0:return v
    for w in (s.get("workers") or {}).values() if isinstance(s.get("workers"),dict) else []:
        for k in ("diff","difficulty","share_diff","pool_diff"):
            try:v=float(w.get(k) or 0)
            except Exception:continue
            if v>0:return v
    for x in reversed(s.get("recent_shares") or []):
        try:v=float(x.get("pool_diff") or x.get("diff") or 0)
        except Exception:continue
        if v>0:return v
    return float(POOL.get("fixed_difficulty") or POOL.get("start_difficulty") or 0)

def estimate_hashrate(s,pd):
    a=[x for x in s.get("recent_shares") or [] if isinstance(x,dict)]
    if not a:return 0.0
    total=sum(float(x.get("pool_diff") or x.get("diff") or pd or 0) for x in a); ts=[_parse_ts(x.get("ts") or x.get("time")) for x in a]; ts=[x for x in ts if x]
    span=max(1.0,(max(ts)-min(ts)).total_seconds()) if len(ts)>1 else max(5.0,5*len(a))
    return total*(2**32)/span if total else 0.0

def wallet_balances():
    wallets,werr=rpc("listwallets"); loaded=bool(wallets is not None and "mining" in (wallets or []))
    for method in ("getbalances","getwalletinfo"):
        res,_=rpc(method)
        if not res:continue
        if method=="getbalances":
            mine=res.get("mine") or {}; return {"confirmed":float(mine.get("trusted") or 0),"unconfirmed":float(mine.get("untrusted_pending") or 0)+float(mine.get("immature") or 0),"wallet_loaded":loaded,"wallet_error":werr}
        return {"confirmed":float(res.get("balance") or 0),"unconfirmed":float(res.get("unconfirmed_balance") or 0)+float(res.get("immature_balance") or 0),"wallet_loaded":loaded,"wallet_error":werr}
    return {"confirmed":0.0,"unconfirmed":0.0,"wallet_loaded":loaded,"wallet_error":werr}

def build_payload():
    s=merge_runtime_stats(load_stats(),parse_stratum_log()); info,info_err=rpc("getblockchaininfo"); net,_=rpc("getnetworkinfo"); gbt,_=rpc("getblocktemplate",[{"rules":["segwit"]}]); tip=info or {}
    height=int(tip.get("blocks") or s.get("round_height") or 0); headers=int(tip.get("headers") or height); difficulty=float(tip.get("difficulty") or s.get("network_diff") or 0); connections=int((net or {}).get("connections") or 0); synced=bool(info) and not tip.get("initialblockdownload",True) and height>=max(headers-1,0)
    ok=int(s.get("shares_ok") or 0); bad=int(s.get("shares_bad") or 0); total=ok+bad; reject=100*bad/total if total else 0; best=float(s.get("best_share_diff") or 0); last=float(s.get("last_share_work") or 0); pd=resolve_pool_diff(s); nd=float(s.get("network_diff") or difficulty or 1); rw=float(s.get("round_work") or 0); effort=float(s.get("round_effort_pct") or (100*rw/nd if nd and rw else 0)); eta=nd/max(last,1e-12)*TARGET_BLOCK_SEC if last and nd else None
    wb=wallet_balances(); holding=HOLDING or s.get("payout") or ""; round_height=int(s.get("round_height") or height); job_height=int((gbt or {}).get("height") or round_height or height); prev=(gbt or {}).get("previousblockhash") or "–"; mat=maturity_info(height,s.get("blocks_log") or []); tip_time=int(tip.get("time") or time.time()); found={int(b.get("height") or 0) for b in s.get("blocks_log") or []}
    return {"synced":synced,"height":height,"headers":headers,"difficulty":difficulty,"network_diff":nd,"difficulty_fmt":fmt_diff(nd),"hashrate_fmt":fmt_hashrate(estimate_hashrate(s,pd)),"confirmed":wb["confirmed"],"unconfirmed":wb["unconfirmed"],"confirmed_fmt":f"{wb['confirmed']:.8f}","unconfirmed_fmt":f"{wb['unconfirmed']:.8f}","wallet_loaded":wb["wallet_loaded"],"wallet_error":wb.get("wallet_error"),"blocks_found":int(s.get("blocks_found") or 0),"rewards_fmt":f"{float(s.get('block_rewards_total') or 0):.8f}","effort_pct":round(effort,3),"best_pct":round(100*best/nd,4) if nd and best else 0,"last_pct":round(100*last/nd,4) if nd and last else 0,"eta_fmt":fmt_duration(eta) if eta else "–","best_share_fmt":fmt_diff(best),"last_share_work_fmt":fmt_diff(last),"shares_ok":ok,"shares_bad":bad,"reject_pct":round(reject,1),"share_diff_fmt":fmt_diff(pd),"last_share_time":s.get("last_share_time"),"last_share_hash":s.get("last_share_hash"),"payout":holding,"addr_ok":bool(holding),"workers":s.get("workers") or {},"connections":connections,"rpc_ok":bool(info),"rpc_error":info_err,"recent_shares":list(reversed(s.get("recent_shares") or []))[:100],"blocks_log":list(reversed(mat))[:1000],"maturity_blocks":COINBASE_MATURITY,"round_height":round_height,"round_work":rw,"round_shares":s.get("round_shares") or 0,"tip_changed_at":s.get("tip_changed_at"),"tip_age":max(0,int(time.time())-tip_time),"network_eta":max(0,TARGET_BLOCK_SEC-(max(0,int(time.time())-tip_time)%TARGET_BLOCK_SEC)),"job_id":f"{job_height}:{prev[:12]}" if prev!="–" else "–","job_height":job_height,"job_prevhash":prev,"job_nbits":(gbt or {}).get("bits") or "–","job_ntime":(gbt or {}).get("curtime") or "–","job_version":(gbt or {}).get("version") or "–","ts":time.strftime("%Y-%m-%d %H:%M:%S"),"height_strip":[{"h":h,"short":str(h)[-3:].zfill(3),"found":h in found,"current":h==height} for h in range(max(0,height-11),height+1)]}

@app.route("/")
def index(): return render_template("dashboard.html", **build_payload())

@app.route("/api/status")
def api_status(): return jsonify(build_payload())

@app.route("/api/health")
def api_health():
    r,_=rpc("getblockchaininfo"); return jsonify({"ok":True,"rpc_ok":bool(r),"ts":time.strftime("%Y-%m-%d %H:%M:%S")})

@app.route("/api/logs")
def api_logs():
    s=merge_runtime_stats(load_stats(),parse_stratum_log())
    return jsonify({"events":load_events(),"snapshot":{"height":s.get("round_height"),"shares_ok":s.get("shares_ok",0),"shares_bad":s.get("shares_bad",0),"blocks_found":s.get("blocks_found",0),"round_effort_pct":s.get("round_effort_pct",0),"round_shares":s.get("round_shares",0),"best_share_diff":s.get("best_share_diff",0),"last_share_work":s.get("last_share_work",0)},"ts":time.strftime("%Y-%m-%d %H:%M:%S")})

if __name__=="__main__":
    mon=CFG.get("monitor") or {}; app.run(host=mon.get("host","0.0.0.0"),port=int(mon.get("port",5050)),debug=False)
