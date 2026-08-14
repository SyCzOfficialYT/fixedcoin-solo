#!/usr/bin/env python3
"""Add reject reason logging to stratum server in-place (container or local)."""
from pathlib import Path
import sys

p = Path(sys.argv[1] if len(sys.argv) > 1 else "stratum/server.py")
t = p.read_text()
changed = 0

repls = [
    (
        'self.send({"id": mid, "result": False, "error": [21, "stale job", None]})\n            self.shares_bad += 1; _bump_worker(self.worker, False); _save_stats()\n            return',
        'self.send({"id": mid, "result": False, "error": [21, "stale job", None]})\n            self.shares_bad += 1; _bump_worker(self.worker, False); _save_stats()\n            emit("WARN", f"REJECT stale job id={job_id}")\n            return',
    ),
    (
        'self.send({"id": mid, "result": False, "error": [23, "low difficulty", None]})\n            self.shares_bad += 1; _bump_worker(self.worker, False); _save_stats()\n            return',
        'self.send({"id": mid, "result": False, "error": [23, "low difficulty", None]})\n            self.shares_bad += 1; _bump_worker(self.worker, False); _save_stats()\n            emit("WARN", f"REJECT low difficulty need={need} work={share_work:.2f} hash={hhex[:16]}")\n            return',
    ),
]
for a, b in repls:
    if a in t and b not in t:
        t = t.replace(a, b, 1)
        changed += 1
        print("patched reject log")

# silence misleading 2-out job log
old = 'emit("INFO", f"Job {job_id} height={height} miner={job[\'value\']/1e8:.8f} "\n                 f"dev={dev_sats/1e8:.8f} FIX (2-out coinbase)")'
# try common variants
import re
t2, n = re.subn(
    r'emit\("INFO", f"Job \{job_id\} height=\{height\} miner=\{job\[.VALUE.\]/1e8:.8f\} "\s*f"dev=\{dev_sats/1e8:.8f\}[^\n]+\)',
    'emit("INFO", f"Job {job_id} height={height} value={job[\'value\']/1e8:.8f} FIX (segwit coinbase)")',
    t,
)
if n:
    t = t2
    changed += n
    print("job log line patched", n)
else:
    t2, n = re.subn(
        r'emit\("INFO", f"Job \{job_id\} height=\{height\} miner=.*?coinbase\)"\)',
        'emit("INFO", f"Job {job_id} height={height} value={job[\'value\']/1e8:.8f} FIX (segwit coinbase)")',
        t,
        count=1,
        flags=re.S,
    )
    if n:
        t = t2
        changed += 1
        print("job log line patched loose")

p.write_text(t)
print("changed", changed, "file", p)
