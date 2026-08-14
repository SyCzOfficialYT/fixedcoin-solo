#!/usr/bin/env python3
"""Bootstrap: build FIX stratum into server_full.py then run it."""
import ast, re, runpy, sys, urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
FULL = HERE / "server_full.py"
URL = "https://raw.githubusercontent.com/SyCzOfficialYT/freecash-coin/a88d89675b/stratum/server.py"

def adapt(t: str) -> str:
    t = t.replace('job_interval", 20)', 'job_interval", 30)')
    t = t.replace("blog[-20:]", "blog[-1000:]")
    t = t.replace("+ 14400", "+ 100")
    t = t.replace(" FCH", " FIX")
    t = t.replace("FreeCash", "FixedCoin")
    t = t.replace("/FCH-Solo/", "/FIX-Solo/")
    t = re.sub(r"^DEV_ADDRESS\s*=\s*.*\n", "", t, flags=re.M)
    t = "\n".join(l for l in t.splitlines() if "DEV_ADDRESS" not in l) + "\n"
    t = re.sub(r"^\s*self\.dev_spk\s*=.*\n", "", t, flags=re.M)
    t = t.replace(", self.dev_spk", "")
    single = (
        "def build_coinbase_parts(height, miner_value_sats, miner_spk, en1_size=4, en2_size=4, *args, **kwargs):\n"
        "    tag = b\"/FIX-Solo/\"\n"
        "    height_script = bip34_height(height)\n"
        "    scriptsig_len = len(height_script) + en1_size + en2_size + len(tag)\n"
        "    part1 = struct.pack(\"<I\", 2) + b\"\\x01\" + b\"\\x00\" * 32 + struct.pack(\"<I\", 0xFFFFFFFF)\n"
        "    part1 += encode_varint(scriptsig_len) + height_script\n"
        "    part2 = tag + struct.pack(\"<I\", 0xFFFFFFFF) + b\"\\x01\"\n"
        "    part2 += struct.pack(\"<Q\", int(miner_value_sats))\n"
        "    part2 += encode_varint(len(miner_spk)) + miner_spk\n"
        "    part2 += struct.pack(\"<I\", 0)\n"
        "    return binascii.hexlify(part1).decode(), binascii.hexlify(part2).decode()\n\n"
    )
    t = re.sub(r"def build_coinbase_parts\(.*?
(?=def )", single, t, count=1, flags=re.S)
    a = "if job is not None and clean:\n                broadcast_job(clean=True)"
    b = "if job is not None:\n                if clean:\n                    broadcast_job(clean=True)\n                else:\n                    broadcast_job(clean=False)"
    if a in t:
        t = t.replace(a, b, 1)
    return t

if FULL.exists():
    FULL.unlink()
print("Fetching stratum base…")
raw = urllib.request.urlopen(URL, timeout=60).read().decode()
adapted = adapt(raw)
ast.parse(adapted)
assert "DEV_ADDRESS" not in adapted
FULL.write_text(adapted)
print("Wrote", FULL, FULL.stat().st_size)
sys.argv[0] = str(FULL)
runpy.run_path(str(FULL), run_name="__main__")
