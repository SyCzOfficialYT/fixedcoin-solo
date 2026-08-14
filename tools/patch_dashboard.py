#!/usr/bin/env python3
"""Write EXACT FreeCash full solo dashboard (heightStrip, Live Competition, timeBar) — FIX branding."""
import base64, zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
chunks = []
for i in range(3):
    p = HERE / ("d.b64.%d" % i)
    chunks.append(p.read_text().strip())
data = zlib.decompress(base64.b64decode("".join(chunks)))
out = HERE.parent / "monitor" / "templates" / "dashboard.html"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_bytes(data)
print("dashboard written", len(data))
assert b"heightStrip" in data
assert b"Live Competition" in data
assert b"FIX Solo" in data
