#!/usr/bin/env python3
"""Apply the FixedCoin-specific data contract to the exact FreeCash dashboard backend."""
from pathlib import Path
import re

p = Path('/app/monitor/app.py')
s = p.read_text()

# The exact FreeCash UI expects these live-job fields. Keep them sourced from
# persisted stratum state when available, with chain-tip fallbacks.
marker = 'def payload():\n'
helper = r'''def _job_fields(stats, info):
    job = stats.get("job") if isinstance(stats.get("job"), dict) else {}
    return {
        "job_id": stats.get("job_id") or job.get("id"),
        "job_height": stats.get("job_height") or job.get("height") or info.get("blocks"),
        "job_prevhash": stats.get("job_prevhash") or job.get("prevhash") or job.get("previousblockhash"),
        "job_nbits": stats.get("job_nbits") or job.get("nbits") or info.get("bits"),
        "job_ntime": stats.get("job_ntime") or job.get("ntime") or info.get("time"),
        "job_version": stats.get("job_version") or job.get("version"),
    }

def _fmt_age(seconds):
    if seconds is None: return "–"
    return fmt_time(max(0, seconds))

def _network_eta(net_diff, hr):
    if not hr or not net_diff: return None
    return (float(net_diff) * (2 ** 32)) / float(hr)

'''
if marker not in s:
    raise SystemExit('payload marker not found')
if 'def _job_fields(' not in s:
    s = s.replace(marker, helper + marker, 1)

old = '    rewards=sum(float(x.get("reward") or 0) for x in blocks)\n    effort=min(100,100*best/nd) if nd else 0; last_pct=min(100,100*last/nd) if nd else 0; eta=(nd*2**32/hr) if hr else None\n'
new = '''    rewards=sum(float(x.get("reward") or 0) for x in blocks)
    # A freshly found coinbase can exist in stratum state before Core's wallet
    # indexes it. Show that reward as immature immediately, but never after the
    # maturity height and never on top of an already visible wallet amount.
    log_immature=sum(float(x.get("reward") or 0) for x in blocks if int(x.get("left") or 0) > 0)
    visible_unconfirmed=pending+immature
    unconfirmed=max(visible_unconfirmed, log_immature)
    effort=min(100,100*best/nd) if nd else 0; last_pct=min(100,100*last/nd) if nd else 0; eta=(nd*2**32/hr) if hr else None
    jobs=_job_fields(s, info or {})
    tip_time=(info or {}).get("time")
    tip_age=(time.time()-float(tip_time)) if tip_time else None
    network_eta=_network_eta(nd, hr)
'''
if old not in s:
    raise SystemExit('payload reward block not found')
s = s.replace(old, new, 1)

oldret = '"confirmed":confirmed,"confirmed_fmt":f"{confirmed:.8f}","unconfirmed":pending+immature,"unconfirmed_fmt":f"{pending+immature:.8f}",'
newret = '"confirmed":confirmed,"confirmed_fmt":f"{confirmed:.8f}","unconfirmed":unconfirmed,"unconfirmed_fmt":f"{unconfirmed:.8f}",'
if oldret not in s:
    raise SystemExit('wallet return contract not found')
s = s.replace(oldret, newret, 1)

needle = '"maturity_blocks":COINBASE_MATURITY,"ts":time.strftime("%Y-%m-%d %H:%M:%S")}'
replacement = '"maturity_blocks":COINBASE_MATURITY,"tip_age":tip_age,"tip_age_fmt":_fmt_age(tip_age),"network_eta":network_eta,"network_eta_fmt":fmt_time(network_eta),**jobs,"ts":time.strftime("%Y-%m-%d %H:%M:%S")} '
if needle not in s:
    raise SystemExit('payload tail not found')
s = s.replace(needle, replacement, 1)

p.write_text(s)
print('FixedCoin dashboard backend contract patched')
