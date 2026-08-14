#!/usr/bin/env python3
"""Bootstrap the adapted FixedCoin stratum and run the cached generated server."""
import ast
import os
import re
import runpy
import sys
import urllib.request
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

    old_gbt = 'rpc("getblocktemplate", [{"rules": []}]) or rpc("getblocktemplate", [])'
    new_gbt = 'rpc("getblocktemplate", [{"rules": ["segwit"]}])'
    if old_gbt not in t:
        raise RuntimeError("getblocktemplate pattern missing")
    t = t.replace(old_gbt, new_gbt, 1)

    fixed_marker = 'MAX_DIFF = int(cfg["pool"].get("vardiff_max", 50_000_000))'
    if fixed_marker not in t:
        raise RuntimeError("vardiff_max pattern missing")
    t = t.replace(
        fixed_marker,
        fixed_marker + '\nFIXED_DIFF = int(cfg["pool"].get("fixed_difficulty", 13354))',
        1,
    )

    start_fixed = t.find("def parse_fixed_diff(")
    if start_fixed < 0:
        raise RuntimeError("parse_fixed_diff not found")
    rest_fixed = t[start_fixed:]
    m_fixed = re.search(r"\ndef [a-zA-Z_]", rest_fixed[1:])
    if not m_fixed:
        raise RuntimeError("end of parse_fixed_diff not found")
    end_fixed = start_fixed + 1 + m_fixed.start()
    fixed_parser = (
        "def parse_fixed_diff(*candidates):\n"
        "    \"\"\"Parse an explicitly requested miner difficulty from password/worker.\"\"\"\n"
        "    for raw in candidates:\n"
        "        if not raw or not isinstance(raw, str):\n"
        "            continue\n"
        "        m = re.search(r\"(?:^|[;,\\s])(?:d|diff)\\s*[=:]\\s*(\\d+(?:\\.\\d+)?)\", raw, re.I)\n"
        "        if not m:\n"
        "            m = re.match(r\"^(?:d|diff)\\s*[=:]\\s*(\\d+(?:\\.\\d+)?)$\", raw.strip(), re.I)\n"
        "        if not m:\n"
        "            continue\n"
        "        try:\n"
        "            d = float(m.group(1))\n"
        "        except (TypeError, ValueError):\n"
        "            continue\n"
        "        if 16 <= d <= MAX_DIFF:\n"
        "            return int(round(d))\n"
        "    return None\n\n"
    )
    t = t[:start_fixed] + fixed_parser + t[end_fixed:]

    start = t.find("def build_coinbase_parts(")
    if start < 0:
        raise RuntimeError("build_coinbase_parts not found")
    rest = t[start:]
    m = re.search(r"\ndef [a-zA-Z_]", rest[1:])
    if not m:
        raise RuntimeError("end of build_coinbase_parts not found")
    end = start + 1 + m.start()
    single = (
        "def build_coinbase_parts(height, miner_value_sats, miner_spk, en1_size=4, en2_size=4, *args, **kwargs):\n"
        "    tag = b'/FIX-Solo/'\n"
        "    height_script = bip34_height(height)\n"
        "    scriptsig_len = len(height_script) + en1_size + en2_size + len(tag)\n"
        "    part1 = struct.pack('<I', 2) + bytes([1]) + bytes(32) + struct.pack('<I', 0xFFFFFFFF)\n"
        "    part1 += encode_varint(scriptsig_len) + height_script\n"
        "    part2 = tag + struct.pack('<I', 0xFFFFFFFF) + bytes([1])\n"
        "    part2 += struct.pack('<Q', int(miner_value_sats))\n"
        "    part2 += encode_varint(len(miner_spk)) + miner_spk\n"
        "    part2 += struct.pack('<I', 0)\n"
        "    return binascii.hexlify(part1).decode(), binascii.hexlify(part2).decode()\n\n"
    )
    t = t[:start] + single + t[end:]

    t = "\n".join(
        ln for ln in t.splitlines()
        if "DEV_ADDRESS" not in ln and "dev_spk" not in ln
    ) + "\n"

    a = "if job is not None and clean:\n                broadcast_job(clean=True)"
    b = (
        "if job is not None:\n"
        "                if clean:\n"
        "                    broadcast_job(clean=True)\n"
        "                else:\n"
        "                    broadcast_job(clean=False)"
    )
    if a in t:
        t = t.replace(a, b, 1)
    return t


def generate_server() -> None:
    print("Fetching stratum base…", flush=True)
    raw = urllib.request.urlopen(URL, timeout=60).read().decode()
    adapted = adapt(raw)
    ast.parse(adapted)
    assert "DEV_ADDRESS" not in adapted and "dev_spk" not in adapted
    assert '"segwit"' in adapted
    assert "FIXED_DIFF" in adapted
    FULL.write_text(adapted)
    print("Wrote", FULL, FULL.stat().st_size, flush=True)


# Docker image builds call this once. Runtime NEVER needs the GitHub/raw URL.
if os.environ.get("STRATUM_BUILD_ONLY") == "1":
    generate_server()
    raise SystemExit(0)

# Keep the generated server. Runtime startup is local and does not fetch GitHub.
if not FULL.exists() or FULL.stat().st_size < 1000:
    generate_server()

sys.argv[0] = str(FULL)
runpy.run_path(str(FULL), run_name="__main__")
