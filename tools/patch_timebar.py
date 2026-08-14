#!/usr/bin/env python3
"""Stabilize FixedCoin 10-minute round time bar on the full solo dashboard."""
from pathlib import Path
import re
import sys

p = Path(sys.argv[1] if len(sys.argv) > 1 else "monitor/templates/dashboard.html")
t = p.read_text(encoding="utf-8")

t = t.replace(
    "const TARGET_BLOCK_SEC=600;",
    "let TARGET_BLOCK_SEC=600; let _lastRoundStartStr=null;",
)
t = t.replace(
    "const TARGET_BLOCK_SEC = 600;",
    "let TARGET_BLOCK_SEC=600; let _lastRoundStartStr=null;",
)

old = "try{_roundStartedMs=parseUtc(d.round_started_at)||parseUtc(d.tip_changed_at);tickRoundClock()}catch(e){}"
new = (
    "try{if(d.target_block_sec)TARGET_BLOCK_SEC=+d.target_block_sec||600;"
    "const rs=d.round_started_at||d.tip_changed_at;"
    "if(rs&&rs!==_lastRoundStartStr){_lastRoundStartStr=rs;_roundStartedMs=parseUtc(rs);}"
    "tickRoundClock()}catch(e){}"
)
if old in t:
    t = t.replace(old, new)
    print("applyStatus hook patched")
elif "_lastRoundStartStr" in t:
    print("applyStatus hook already patched")
else:
    print("WARN: applyStatus hook pattern not found")

if "tgtLab=fmtClock(tgt)" not in t:
    t2, n = re.subn(
        r"function tickRoundClock\(\)\{[^}]+\}",
        "function tickRoundClock(){ const bar=document.getElementById('timeBar'), lab=document.getElementById('timeLabel'); if(!bar||!lab)return; const tgt=TARGET_BLOCK_SEC||600; const tgtLab=fmtClock(tgt); if(!_roundStartedMs){ lab.textContent='– / ~'+tgtLab; lab.className='time-label'; bar.style.width='0%'; bar.className='progress-fill time-ok'; return;} const e=Math.max(0,(Date.now()-_roundStartedMs)/1000), o=e>tgt; bar.style.width=Math.min(100,(e/tgt)*100)+'%'; bar.className='progress-fill '+(o?'time-over':'time-ok'); lab.className='time-label '+(o?'over':'ok'); lab.textContent=fmtClock(e)+' / ~'+tgtLab+(o?'  (überfällig)':''); }",
        t,
        count=1,
    )
    if n:
        t = t2
        print("tickRoundClock patched")
    else:
        print("WARN: tickRoundClock pattern not found")
else:
    print("tickRoundClock already patched")

p.write_text(t, encoding="utf-8")
print("wrote", p, "bytes", p.stat().st_size)
