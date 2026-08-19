#!/usr/bin/env python3
"""FixedCoin Solo dashboard backed by FixedCoin RPC/wallet."""
from flask import Flask, render_template, jsonify, make_response
from pathlib import Path
from datetime import datetime, timezone
from requests.auth import HTTPBasicAuth
import json, os, re, time, requests, yaml
ROOT=Path(__file__).resolve().parent.parent
CONFIG_PATH=ROOT/"config"/"config.yaml"
STATS_PATH=Path(os.environ.get("STATS_PATH", ROOT/"data"/"stats.json"))
STRATUM_LOG=Path(os.environ.get("STRATUM_LOG", ROOT/"data"/"stratum.log"))
EVENTS_PATH=Path(os.environ.get("EVENTS_PATH", ROOT/"data"/"events.jsonl"))
COINBASE_MATURITY=int(os.environ.get("COINBASE_MATURITY","100"))
RPC_TIMEOUT=float(os.environ.get("DASH_RPC_TIMEOUT","5"))
app=Flask(__name__,template_folder="templates")
def cfg():
    try:return yaml.safe_load(CONFIG_PATH.read_text()) or {}
    except Exception:return {}
CFG=cfg(); RPC_CFG=CFG.get("rpc") or {}; POOL=CFG.get("pool") or {}
RPC_URL=f"http://{RPC_CFG.get('host','127.0.0.1')}:{int(RPC_CFG.get('port',24761))}"
RPC_AUTH=HTTPBasicAuth(RPC_CFG.get('user','fixrpc'),RPC_CFG.get('password',''))
PAYOUT=str(POOL.get("payout_address") or "").strip()
def rpc(method,params=None,timeout=RPC_TIMEOUT):
    try:
        r=requests.post(RPC_URL,json={"jsonrpc":"1.0","id":"dashboard","method":method,"params":params or []},auth=RPC_AUTH,timeout=timeout)
        try:d=r.json()
        except Exception:return None,f"HTTP {r.status_code}: invalid JSON"
        if d.get("error"):return None,d["error"]
        if r.status_code>=400:return None,f"HTTP {r.status_code}"
        return d.get("result"),None
    except Exception as e:return None,str(e)
def read_lines(path,n=5000):
    try:return path.read_text(errors="replace").splitlines()[-n:] if path.exists() else []
    except Exception:return []
def load_stats():
    try:
        d=json.loads(STATS_PATH.read_text()) if STATS_PATH.exists() else {}
        return d if isinstance(d,dict) else {}
    except Exception:return {}
def parse_stratum():
    accepted=[]; rejected=0; workers={}; current_worker=None; current_diff=float(POOL.get("fixed_difficulty") or POOL.get("start_difficulty") or 1); round_height=0; round_net=0.0; blocks=[]
    for line in read_lines(STRATUM_LOG):
        m=re.search(r"authorize\s+(\S+).*?(?:diff|share_diff)\s*[=:]\s*([0-9.]+)",line,re.I)
        if m:current_worker=m.group(1); current_diff=float(m.group(2)); workers.setdefault(current_worker,{"ok":0,"bad":0,"diff":current_diff})
        m=re.search(r"(?:NEW ROUND|round).*?height[=:](\d+).*?(?:netdiff|network_diff)[=:]([0-9.]+)",line,re.I)
        if m:round_height=int(m.group(1)); round_net=float(m.group(2))
        m=re.search(r"ACCEPT\s+#(\d+)\s+work=([0-9.]+).*?(?:pool|pool_diff)=([0-9.]+).*?hash=([0-9a-fA-F]+)",line,re.I)
        if m:
            num,work,pd,h=m.groups(); work=float(work); pd=float(pd); pct=100*work/(round_net or 1)
            accepted.append({"ts":line[:19],"num":int(num),"work":work,"pool_diff":pd,"net_diff":round_net,"pct":pct,"hash":h[:16],"height":round_height or None,"worker":current_worker,"ok":True})
            if current_worker:workers.setdefault(current_worker,{"ok":0,"bad":0,"diff":current_diff})["ok"]+=1
        elif re.search(r"\bREJECT\b",line,re.I):
            rejected+=1
            if current_worker:workers.setdefault(current_worker,{"ok":0,"bad":0,"diff":current_diff})["bad"]+=1
        m=re.search(r"BLOCK ACCEPTED.*?height=(\d+).*?hash=([0-9a-fA-F]{16,64})(?:.*?reward=([0-9.]+))?",line,re.I)
        if m:
            h,bh,reward=m.groups(); blocks.append({"ts":line[:19],"height":int(h),"hash":bh,"reward":float(reward or 0),"address":PAYOUT,"mature_at_height":int(h)+COINBASE_MATURITY})
    return {"shares_ok":len(accepted),"shares_bad":rejected,"recent_shares":accepted[-100:],"workers":workers,"round_height":round_height,"network_diff":round_net,"best_share_diff":max((x["work"] for x in accepted),default=0),"last_share_work":accepted[-1]["work"] if accepted else 0,"last_share_time":accepted[-1]["ts"] if accepted else None,"last_share_hash":accepted[-1]["hash"] if accepted else None,"blocks_log":blocks[-1000:]}
def wallet_balances():
    r,e=rpc("getbalances")
    if isinstance(r,dict) and isinstance(r.get("mine"),dict):
        m=r["mine"]; return float(m.get("trusted") or 0),float(m.get("untrusted_pending") or 0),float(m.get("immature") or 0),e
    r,e2=rpc("getwalletinfo")
    if isinstance(r,dict):return float(r.get("balance") or 0),float(r.get("unconfirmed_balance") or 0),float(r.get("immature_balance") or 0),None
    return 0.0,0.0,0.0,e or e2
def wallet_blocks():
    r,e=rpc("listtransactions",["*",1000,0,True],timeout=8); rows={}
    if not isinstance(r,list):return [],e
    for tx in r:
        if not isinstance(tx,dict) or str(tx.get("category","")).lower() not in {"immature","generate"}:continue
        if tx.get("generated") is not True and tx.get("category")!="immature":continue
        if tx.get("address") and PAYOUT and tx.get("address")!=PAYOUT:continue
        try:h=int(tx.get("blockheight")); amount=float(tx.get("amount") or 0)
        except Exception:continue
        if h<=0 or amount<=0:continue
        key=str(tx.get("txid") or f"{h}:{tx.get('blockhash','')}")
        row=rows.setdefault(key,{"ts":time.strftime("%Y-%m-%d %H:%M:%S",time.gmtime(tx.get("blocktime") or tx.get("time") or time.time())),"height":h,"hash":str(tx.get("blockhash") or "")[:16],"txid":str(tx.get("txid") or ""),"reward":0.0,"address":PAYOUT,"mature_at_height":h+COINBASE_MATURITY,"confirmations":0,"category":"immature"})
        row["reward"]+=amount; row["confirmations"]=max(row["confirmations"],int(tx.get("confirmations") or 0)); row["category"]="generate" if str(tx.get("category"))=="generate" else row["category"]
    return list(rows.values()),None
def chain_block(height):
    bh,e=rpc("getblockhash",[height],timeout=3)
    if not bh:return None
    blk,e=rpc("getblock",[bh,2],timeout=4)
    if not isinstance(blk,dict):return None
    txs=blk.get("tx") or []
    if not txs or not isinstance(txs[0],dict):return None
    tx=txs[0]
    if not tx.get("vin") or not tx["vin"][0].get("coinbase"):return None
    reward=0.0; pays=False
    for v in tx.get("vout") or []:
        spk=v.get("scriptPubKey") or {}; adds=spk.get("addresses") or ([spk.get("address")] if spk.get("address") else [])
        if PAYOUT and PAYOUT in adds:pays=True; reward+=float(v.get("value") or 0)
    if not pays:return None
    return {"ts":time.strftime("%Y-%m-%d %H:%M:%S",time.gmtime(blk.get("time") or time.time())),"height":height,"hash":bh[:16],"txid":tx.get("txid",""),"reward":reward,"address":PAYOUT,"mature_at_height":height+COINBASE_MATURITY,"confirmations":1,"category":"immature"}
def fmt_diff(v):
    try:v=float(v)
    except Exception:return "0"
    for div,s in ((1e9,"G"),(1e6,"M"),(1e3,"K")):
        if v>=div:return f"{v/div:.2f} {s}"
    return f"{v:.2f}"
def fmt_hr(v):
    try:v=float(v)
    except Exception:return "–"
    for div,s in ((1e12,"TH/s"),(1e9,"GH/s"),(1e6,"MH/s"),(1e3,"kH/s")):
        if v>=div:return f"{v/div:.2f} {s}"
    return f"{v:.2f} H/s" if v else "–"
def fmt_time(sec):
    if sec is None:return "–"
    sec=max(0,int(sec))
    if sec<60:return f"{sec}s"
    if sec<3600:return f"{sec//60}m {sec%60}s"
    if sec<86400:return f"{sec//3600}h {(sec%3600)//60}m"
    return f"{sec//86400}d {(sec%86400)//3600}h"
def difficulty_target(diff):
    try:diff=float(diff)
    except Exception:return "", ""
    if diff<=0:return "", ""
    diff1=int("00000000FFFF0000000000000000000000000000000000000000000000000000",16)
    target=max(1,int(diff1/diff)); size=(target.bit_length()+7)//8
    mant=(target << (8*(3-size))) if size<=3 else (target >> (8*(size-3)))
    compact=((size<<24)|(mant & 0x007fffff)) & 0xffffffff
    return f"{target:064x}",f"{compact:08x}"
def payload():
    info,info_err=rpc("getblockchaininfo"); net,_=rpc("getnetworkinfo"); s=load_stats(); log=parse_stratum(); shares=log if log["shares_ok"] or log["shares_bad"] else s
    height=int((info or {}).get("blocks") or log.get("round_height") or 0); headers=int((info or {}).get("headers") or height); diff=float((info or {}).get("difficulty") or log.get("network_diff") or 0); nd=diff or float(log.get("network_diff") or 1)
    recent=list(shares.get("recent_shares") or [])[-100:]; best=max([float(x.get("work") or 0) for x in recent],default=float(shares.get("best_share_diff") or 0)); last=float((recent[-1] if recent else {}).get("work") or shares.get("last_share_work") or 0); ts=[]
    for x in recent:
        try:ts.append(datetime.strptime(str(x.get("ts"))[:19],"%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc))
        except Exception:pass
    span=max(1,(max(ts)-min(ts)).total_seconds()) if len(ts)>1 else 5; hr=sum(float(x.get("pool_diff") or POOL.get("fixed_difficulty") or 1) for x in recent)*(2**32)/span if recent else 0
    confirmed,pending,immature,werr=wallet_balances(); wblocks,_=wallet_blocks(); found_blocks=list(log.get("blocks_log") or []); merged={str(x.get("txid") or x.get("hash") or x.get("height")):x for x in wblocks}
    for b in found_blocks:merged[str(b.get("txid") or b.get("hash") or b.get("height"))]=b
    for b in list(merged.values()):
        try:
            h=int(b.get("height")); cb=chain_block(h)
            if cb:merged[str(cb.get("txid") or cb.get("hash") or h)]=cb
            conf=max(0,height-h+1); b["confirmations"]=conf; b["mature_at_height"]=int(b.get("mature_at_height") or h+COINBASE_MATURITY); b["left"]=max(0,b["mature_at_height"]-height); b["mature"]=b["left"]==0; b["spendable"]=b["left"]==0; b["confs"]=min(COINBASE_MATURITY,conf)
        except Exception:pass
    blocks=sorted(merged.values(),key=lambda x:int(x.get("height") or 0),reverse=True)[:1000]; rewards=sum(float(x.get("reward") or 0) for x in blocks); effort=min(100,100*best/nd) if nd else 0; last_pct=min(100,100*last/nd) if nd else 0; eta=(nd*2**32/hr) if hr else None; target_hex,nbits=difficulty_target(diff)
    return {"synced":bool(info) and not bool((info or {}).get("initialblockdownload",False)),"height":height,"headers":headers,"difficulty":diff,"difficulty_fmt":fmt_diff(diff),"hashrate_fmt":fmt_hr(hr),"balance_fmt":f"{confirmed:.8f}","immature_fmt":f"{immature:.8f}","immature":immature,"confirmed":confirmed,"confirmed_fmt":f"{confirmed:.8f}","unconfirmed":pending+immature,"unconfirmed_fmt":f"{pending+immature:.8f}","blocks_found":len(blocks),"rewards_fmt":f"{rewards:.8f}","effort_pct":round(effort,4),"best_pct":round(effort,4),"best_share_diff":best,"last_pct":round(last_pct,4),"eta_fmt":fmt_time(eta),"best_share_fmt":fmt_diff(best),"last_share_work_fmt":fmt_diff(last),"shares_ok":int(shares.get("shares_ok") or 0),"shares_bad":int(shares.get("shares_bad") or 0),"reject_pct":round(100*int(shares.get("shares_bad") or 0)/max(1,int(shares.get("shares_ok") or 0)+int(shares.get("shares_bad") or 0)),1),"share_diff":float(POOL.get("fixed_difficulty") or POOL.get("start_difficulty") or 1),"share_diff_fmt":fmt_diff(float(POOL.get("fixed_difficulty") or POOL.get("start_difficulty") or 1)),"last_share_time":shares.get("last_share_time"),"last_share_hash":shares.get("last_share_hash"),"payout":PAYOUT,"addr_ok":bool(PAYOUT),"workers":shares.get("workers") or {},"connections":int((net or {}).get("connections") or 0),"rpc_ok":bool(info),"rpc_error":None if info else info_err,"recent_shares":list(reversed(recent)),"blocks_log":blocks,"maturity_blocks":COINBASE_MATURITY,"ts":time.strftime("%Y-%m-%d %H:%M:%S"),"target":target_hex,"nbits":nbits,"protocol":str((net or {}).get("protocolversion") or ""),"verification":f"{(info or {}).get('verificationprogress',0)*100:.2f}%" if info else "–"}
def events(limit=160):
    out=[]
    for raw in read_lines(EVENTS_PATH,limit):
        try:
            e=json.loads(raw)
            if isinstance(e,dict):out.append(e)
        except Exception:pass
    for raw in read_lines(STRATUM_LOG,300):
        if not any(x in raw for x in ("ACCEPT","BLOCK","ERROR","REJECT","authorize","NEW ROUND")):continue
        level="OK" if "ACCEPT" in raw or "BLOCK" in raw else "WARN" if "REJECT" in raw else "ERROR" if "ERROR" in raw else "INFO"; out.append({"ts":raw[:19],"level":level,"msg":raw[20:].strip() if len(raw)>20 else raw})
    return out[-limit:]
@app.after_request
def nocache(r):
    r.headers.update({"Cache-Control":"no-store, no-cache, must-revalidate, max-age=0","Pragma":"no-cache","Expires":"0"}); return r
@app.route("/")
def index():
    p=payload(); return make_response(render_template("dashboard_exact.html",**p).replace("FreeCash","FixedCoin").replace("FCH","FIX"))
@app.route("/api/status")
def api_status():return jsonify(payload())
@app.route("/api/logs")
def api_logs():
    p=payload(); return jsonify({"events":events(),"snapshot":{"height":p["height"],"shares_ok":p["shares_ok"],"shares_bad":p["shares_bad"],"blocks_found":p["blocks_found"],"best_share_diff":p["best_pct"],"last_share_work":p["last_share_work_fmt"],"last_share_time":p["last_share_time"],"last_share_hash":p["last_share_hash"],"workers":list(p["workers"].keys()),"holding":PAYOUT,"balance":p["confirmed"]},"ts":p["ts"]})
if __name__=="__main__":
    mon=CFG.get("monitor") or {}; app.run(host=mon.get("host","0.0.0.0"),port=int(mon.get("port",5050)),debug=False)
