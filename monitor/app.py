#!/usr/bin/env python3
"""FixedCoin Solo dashboard.

Keeps the exact FreeCash dashboard data contract/UI, but all values are
FixedCoin-specific and block history is wallet/chain authoritative.
"""
from flask import Flask, render_template, jsonify, make_response
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
TARGET_BLOCK_SEC = int(os.environ.get("TARGET_BLOCK_SEC", "60"))
DASH_RPC_TIMEOUT = float(os.environ.get("DASH_RPC_TIMEOUT", "5"))

app = Flask(__name__, template_folder="templates")

def load_cfg():
    try: return yaml.safe_load(CONFIG_PATH.read_text()) or {}
    except Exception: return {}

CFG=load_cfg(); RPC=CFG.get("rpc") or {}; POOL=CFG.get("pool") or {}
RPC_HOST=RPC.get("host","127.0.0.1"); RPC_PORT=int(RPC.get("port",24761)); RPC_USER=RPC.get("user","fixrpc"); RPC_PASS=RPC.get("password","")
HOLDING=str(POOL.get("payout_address") or "").strip()

def rpc(method, params=None, timeout=None):
    try:
        r=requests.post(f"http://{RPC_HOST}:{RPC_PORT}",json={"jsonrpc":"1.0","id":"dashboard","method":method,"params":params or []},auth=HTTPBasicAuth(RPC_USER,RPC_PASS),timeout=DASH_RPC_TIMEOUT if timeout is None else timeout)
        r.raise_for_status(); data=r.json()
        if data.get("error"): return None,data["error"]
        return data.get("result"),None
    except Exception as e: return None,str(e)

def load_stats():
    try:
        if STATS_PATH.exists() and STATS_PATH.stat().st_size:
            d=json.loads(STATS_PATH.read_text()); return d if isinstance(d,dict) else {}
    except Exception: pass
    return {}

def read_tail_lines(path,limit=1000):
    try:
        p=Path(path); return p.read_text(errors="replace").splitlines()[-limit:] if p.exists() else []
    except Exception: return []

def parse_ts(s):
    try: return datetime.strptime(str(s)[:19],"%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc) if s else None
    except Exception: return None

def parse_stratum_log():
    lines=read_tail_lines(STRATUM_LOG,5000); accepted=[]; rejected=0; workers={}; current_worker=None; current_diff=0.0; round_height=0; round_netdiff=0.0; best=0.0; last=None; blocks=[]
    auth_re=re.compile(r"authorize\s+(\S+)\s+(?:diff|share_diff)=(\d+(?:\.\d+)?)",re.I); accept_re=re.compile(r"ACCEPT\s+#(\d+)\s+work=([0-9.]+).*?(?:pool|pool_diff)=([0-9.]+).*?(?:round=[0-9.]+%\s+)?hash=([0-9a-fA-F]+)",re.I); reject_re=re.compile(r"REJECT\s+.*?(?:need=([0-9.]+)\s+)?work=([0-9.]+).*?hash=([0-9a-fA-F]+)",re.I); round_re=re.compile(r"NEW ROUND\s+height=(\d+)\s+netdiff=([0-9.]+)",re.I); block_re=re.compile(r"BLOCK ACCEPTED.*?height=(\d+).*?hash=([0-9a-fA-F]{16,64}).*?reward=([0-9.]+)",re.I)
    for line in lines:
        m=auth_re.search(line)
        if m: current_worker=m.group(1); current_diff=float(m.group(2)); workers.setdefault(current_worker,{"ok":0,"bad":0,"diff":current_diff}); continue
        m=round_re.search(line)
        if m: round_height=int(m.group(1)); round_netdiff=float(m.group(2)); continue
        m=accept_re.search(line)
        if m:
            num,work,pd,h=m.groups(); work=float(work); pd=float(pd); last={"ts":line[:19],"num":int(num),"work":work,"pool_diff":pd,"net_diff":round_netdiff,"pct":100*work/round_netdiff if round_netdiff else 0,"hash":h[:16],"height":round_height or None,"ok":True}; accepted.append(last); best=max(best,work)
            if current_worker: workers.setdefault(current_worker,{"ok":0,"bad":0,"diff":current_diff})["ok"]+=1
            continue
        if reject_re.search(line):
            rejected+=1
            if current_worker: workers.setdefault(current_worker,{"ok":0,"bad":0,"diff":current_diff})["bad"]+=1
        m=block_re.search(line)
        if m:
            bh,bhsh,reward=m.groups(); blocks.append({"height":int(bh),"hash":bhsh,"reward":float(reward)})
    return {"shares_ok":len(accepted),"shares_bad":rejected,"recent_shares":accepted[-100:],"workers":workers,"round_height":round_height,"network_diff":round_netdiff,"best_share_diff":best,"last_share_work":last.get("work",0) if last else 0,"last_share_time":last.get("ts") if last else None,"last_share_hash":last.get("hash") if last else None,"blocks_log":blocks[-1000:]}

def merge_stats(a,b):
    out=dict(a or {})
    for k,v in b.items():
        if k in ("recent_shares","workers","blocks_log"):
            if v: out[k]=v
        elif not out.get(k) and v is not None: out[k]=v
    return out

def wallet_balances():
    result,err=rpc("getbalances")
    if isinstance(result,dict) and isinstance(result.get("mine"),dict):
        m=result["mine"]; return {"confirmed":float(m.get("trusted") or 0),"immature":float(m.get("immature") or 0),"pending":float(m.get("untrusted_pending") or 0),"error":None}
    result,err2=rpc("getwalletinfo")
    if isinstance(result,dict): return {"confirmed":float(result.get("balance") or 0),"immature":float(result.get("immature_balance") or 0),"pending":float(result.get("unconfirmed_balance") or 0),"error":None}
    return {"confirmed":0.0,"immature":0.0,"pending":0.0,"error":err or err2}

def _wallet_rows(limit=1000):
    txs,err=rpc("listtransactions",["*",limit,0,True])
    if not isinstance(txs,list): return [],err
    rows={}
    for tx in txs:
        if not isinstance(tx,dict): continue
        cat=str(tx.get("category") or "").lower()
        if cat not in {"immature","generate"} and tx.get("generated") is not True: continue
        if cat=="orphan": continue
        addr=str(tx.get("address") or "").strip()
        if HOLDING and addr and addr!=HOLDING: continue
        try: h=int(tx.get("blockheight")); amount=float(tx.get("amount") or 0)
        except Exception: continue
        if h<=0 or amount<=0: continue
        txid=str(tx.get("txid") or ""); bh=str(tx.get("blockhash") or ""); key=txid or f"{h}:{bh}"
        row=rows.setdefault(key,{"ts":time.strftime("%Y-%m-%d %H:%M:%S",time.gmtime(tx.get("blocktime") or tx.get("time") or time.time())),"height":h,"hash":bh[:16] if bh else "–","txid":txid,"reward":0.0,"address":HOLDING or addr,"mature_at_height":h+COINBASE_MATURITY,"confirmations":0,"category":cat})
        row["reward"]+=amount; row["confirmations"]=max(row["confirmations"],int(tx.get("confirmations") or 0))
        if cat=="generate": row["category"]="generate"
    return list(rows.values()),None

def _chain_rows(seed_rows,height):
    heights=set()
    for b in seed_rows:
        try: heights.add(int(b.get("height") or 0))
        except Exception: pass
    s=load_stats()
    for b in (s.get("blocks_log") or []):
        try: heights.add(int(b.get("height") or 0))
        except Exception: pass
    for b in parse_stratum_log().get("blocks_log") or []:
        try: heights.add(int(b.get("height") or 0))
        except Exception: pass
    if height: heights.update(range(max(1,height-110),height+1))
    rows={}
    for h in sorted(heights):
        bh,_=rpc("getblockhash",[h],timeout=2)
        if not bh: continue
        blk,_=rpc("getblock",[bh,2],timeout=3)
        if not isinstance(blk,dict): continue
        txs=blk.get("tx") or []
        if not txs or not isinstance(txs[0],dict): continue
        tx=txs[0]
        if not tx.get("vin") or not tx["vin"][0].get("coinbase"): continue
        reward=0.0; pays=False
        for v in tx.get("vout") or []:
            spk=v.get("scriptPubKey") or {}; addrs=spk.get("addresses") or ([spk.get("address")] if spk.get("address") else [])
            if HOLDING and HOLDING in addrs:
                pays=True
                try: reward+=float(v.get("value") or 0)
                except Exception: pass
        if not pays: continue
        key=tx.get("txid") or bh; conf=max(0,height-h+1)
        rows[key]={"ts":time.strftime("%Y-%m-%d %H:%M:%S",time.gmtime(blk.get("time") or time.time())),"height":h,"hash":bh[:16],"txid":tx.get("txid",""),"reward":reward,"address":HOLDING,"mature_at_height":h+COINBASE_MATURITY,"confirmations":conf,"category":"generate" if conf>COINBASE_MATURITY else "immature"}
    return list(rows.values())

def wallet_coinbase_log(height):
    rows,err=_wallet_rows(); chain=_chain_rows(rows,height) if err is None else []
    merged={str(r.get("txid") or r.get("hash") or r.get("height")):r for r in rows}
    for r in chain: merged[str(r.get("txid") or r.get("hash") or r.get("height"))]=r
    return sorted(merged.values(),key=lambda x:int(x.get("height") or 0),reverse=True),err

def maturity_info(height,rows):
    out=[]
    for b in rows or []:
        try: h=int(b.get("height") or 0)
        except Exception: continue
        if not h: continue
        mature_at=int(b.get("mature_at_height") or h+COINBASE_MATURITY); left=max(0,mature_at-height)
        out.append({**b,"confs":min(COINBASE_MATURITY,max(0,height-h+1)),"left":left,"remaining":left,"spendable":left==0,"mature":left==0,"mature_at_height":mature_at})
    return out

def fmt_diff(v):
    try:v=float(v)
    except Exception:return "0"
    if v>=1e9:return f"{v/1e9:.2f} G"
    if v>=1e6:return f"{v/1e6:.2f} M"
    if v>=1e3:return f"{v/1e3:.2f} k"
    return f"{v:.2f}"

def fmt_hashrate(v):
    try:v=float(v)
    except Exception:return "–"
    for scale,unit in ((1e12,"TH/s"),(1e9,"GH/s"),(1e6,"MH/s"),(1e3,"kH/s")):
        if v>=scale:return f"{v/scale:.2f} {unit}"
    return f"{v:.2f} H/s" if v>0 else "–"

def fmt_duration(sec):
    if sec is None:return "–"
    sec=max(0,int(sec))
    if sec<60:return f"{sec}s"
    if sec<3600:return f"{sec//60}m {sec%60}s"
    if sec<86400:return f"{sec//3600}h {(sec%3600)//60}m"
    return f"{sec//86400}d {((sec%86400)//3600)}h"

def build_payload():
    s=merge_stats(load_stats(),parse_stratum_log()); info,info_err=rpc("getblockchaininfo"); net,_=rpc("getnetworkinfo")
    height=int((info or {}).get("blocks") or s.get("round_height") or 0); headers=int((info or {}).get("headers") or height); difficulty=float((info or {}).get("difficulty") or s.get("network_diff") or 0); nd=difficulty or float(s.get("network_diff") or 1)
    ok=int(s.get("shares_ok") or 0); bad=int(s.get("shares_bad") or 0); total=ok+bad; pd=float(POOL.get("fixed_difficulty") or POOL.get("start_difficulty") or 1)
    for x in reversed(s.get("recent_shares") or []):
        try:
            q=float(x.get("pool_diff") or 0)
            if q>0: pd=q; break
        except Exception: pass
    best=float(s.get("best_share_diff") or 0); last=float(s.get("last_share_work") or 0); ts=[parse_ts(x.get("ts")) for x in s.get("recent_shares") or []]; ts=[x for x in ts if x]; span=max(1,(max(ts)-min(ts)).total_seconds()) if len(ts)>1 else 5; hr=sum(float(x.get("pool_diff") or pd) for x in s.get("recent_shares") or [])*(2**32)/span if s.get("recent_shares") else 0
    wb=wallet_balances(); rows,werr=wallet_coinbase_log(height); mat=maturity_info(height,rows); found=len(rows); effort=min(100,100*best/nd) if nd and best else 0; last_pct=min(100,100*last/nd) if nd and last else 0; eta=(nd*2**32/hr) if hr>0 else None; synced=bool(info) and not bool((info or {}).get("initialblockdownload",False)) and height>=max(headers-1,0)
    return {"synced":synced,"height":height,"headers":headers,"difficulty":difficulty,"difficulty_fmt":fmt_diff(difficulty),"hashrate_fmt":fmt_hashrate(hr),"balance_fmt":f"{wb['confirmed']:.8f}","immature_fmt":f"{wb['immature']:.8f}","confirmed":wb["confirmed"],"unconfirmed":wb["pending"]+wb["immature"],"confirmed_fmt":f"{wb['confirmed']:.8f}","unconfirmed_fmt":f"{wb['pending']+wb['immature']:.8f}","blocks_found":found,"rewards_fmt":f"{sum(float(r.get('reward') or 0) for r in rows):.8f}","effort_pct":round(effort,4),"best_pct":round(effort,4),"last_pct":round(last_pct,4),"eta_fmt":fmt_duration(eta) if eta else "–","best_share_fmt":fmt_diff(best),"last_share_work_fmt":fmt_diff(last),"shares_ok":ok,"shares_bad":bad,"reject_pct":round(100*bad/total,1) if total else 0,"share_diff_fmt":fmt_diff(pd),"last_share_time":s.get("last_share_time"),"last_share_hash":s.get("last_share_hash"),"payout":HOLDING,"addr_ok":bool(HOLDING),"workers":s.get("workers") or {},"connections":int((net or {}).get("connections") or 0),"rpc_ok":bool(info),"rpc_error":None,"recent_shares":list(reversed(s.get("recent_shares") or []))[:100],"blocks_log":mat[:1000],"maturity_blocks":COINBASE_MATURITY,"ts":time.strftime("%Y-%m-%d %H:%M:%S")}

def load_events(limit=160):
    out=[]
    if EVENTS_PATH.exists():
        for raw in read_tail_lines(EVENTS_PATH,limit):
            try:
                e=json.loads(raw); out.append(e if isinstance(e,dict) else {})
            except Exception: pass
    for raw in read_tail_lines(STRATUM_LOG,300):
        if not any(x in raw for x in ("ACCEPT","BLOCK","ERROR","REJECT","authorize","NEW ROUND")):continue
        lvl="OK" if "ACCEPT" in raw or "BLOCK" in raw else "WARN" if "REJECT" in raw else "INFO"; out.append({"ts":raw[:19],"level":lvl,"msg":raw[20:].strip() if len(raw)>20 else raw})
    return out[-limit:]

@app.after_request
def no_cache(response):
    response.headers["Cache-Control"]="no-store, no-cache, must-revalidate, max-age=0"; response.headers["Pragma"]="no-cache"; response.headers["Expires"]="0"; return response

@app.route("/")
def index():
    p=build_payload(); html=render_template("dashboard.html",**p); return make_response(html.replace("FreeCash","FixedCoin").replace("FCH","FIX"))

@app.route("/api/status")
def api_status(): return jsonify(build_payload())

@app.route("/api/logs")
def api_logs():
    s=merge_stats(load_stats(),parse_stratum_log()); p=build_payload(); snapshot={"height":p["height"],"shares_ok":p["shares_ok"],"shares_bad":p["shares_bad"],"blocks_found":p["blocks_found"],"best_share_diff":s.get("best_share_diff",0),"last_share_work":s.get("last_share_work",0),"last_share_time":p.get("last_share_time"),"last_share_hash":p.get("last_share_hash"),"workers":list((s.get("workers") or {}).keys()),"holding":HOLDING,"balance":p["confirmed"]}; return jsonify({"events":load_events(),"snapshot":snapshot,"ts":p["ts"]})

if __name__=="__main__":
    mon=CFG.get("monitor") or {}; app.run(host=mon.get("host","0.0.0.0"),port=int(mon.get("port",5050)),debug=False)
