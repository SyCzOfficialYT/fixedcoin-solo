#!/usr/bin/env python3
import base64, zlib, urllib.request
from pathlib import Path
BASE = "https://raw.githubusercontent.com/SyCzOfficialYT/fixedcoin-solo/main/monitor/"
chunks = []
for i in range(2):
    with urllib.request.urlopen(BASE + f"d.b64.{i}", timeout=60) as r:
        chunks.append(r.read().decode().strip())
data = zlib.decompress(base64.b64decode("".join(chunks)))
out = Path(__file__).resolve().parent / "templates" / "dashboard.html"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_bytes(data)
print("dashboard restored", len(data))
assert b"effortBar" in data and b"blocksBody" in data and b"/api/logs" in data
