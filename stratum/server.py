#!/usr/bin/env python3
"""Bootstrap: assemble full server from s.b64.* parts."""
from pathlib import Path
import runpy, sys
here = Path(__file__).resolve().parent
parts = sorted(here.glob("s.b64.*"))
target = here / "server_full.py"
if parts and (not target.exists() or target.stat().st_size < 1000):
    import base64, zlib
    data = zlib.decompress(base64.b64decode("".join(p.read_text().strip() for p in parts)))
    target.write_bytes(data)
    print("assembled stratum", len(data))
if target.exists():
    sys.argv[0] = str(target)
    runpy.run_path(str(target), run_name="__main__")
else:
    raise SystemExit("missing stratum/s.b64.* – run: git pull")
