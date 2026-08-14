#!/usr/bin/env python3
"""Build the FixedCoin stratum from the known-good FreeCash base, locally."""
import ast
import os
import runpy
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
FULL = HERE / "server_full.py"
URL = "https://raw.githubusercontent.com/SyCzOfficialYT/freecash-coin/a88d89675b3a41cc6774e1b975e57e050d4892cc/stratum/server.py"
ADAPT_VERSION = "fixedcoin-fch-dashboard-repair-2026-08-14-v6-gbt-safe"


def replace_function(source: str, name: str, replacement: str) -> str:
    tree = ast.parse(source)
    target = next((n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name), None)
    if target is None:
        raise RuntimeError(f"function {name!r} not found in FreeCash base")
    lines = source.splitlines(keepends=True)
    start = sum(len(x) for x in lines[:target.lineno - 1])
    end = sum(len(x) for x in lines[:target.end_lineno])
    return source[:start] + replacement.rstrip() + "\n" + source[end:]


def adapt(t: str) -> str:
    t = t.replace('job_interval", 20)', 'job_interval", 30)')
    t = t.replace("blog[-20:]", "blog[-1000:]")
    t = t.replace("+ 14400", "+ 100")
    t = t.replace(" FCH", " FIX")
    t = t.replace("FreeCash", "FixedCoin")
    t = t.replace("/FCH-Solo/", "/FIX-Solo/")

    # Keep the known-good FreeCash GBT request. FixedCoin's daemon currently
    # rejects an explicit ["segwit"] request with HTTP 500. If the template
    # contains default_witness_commitment, witness handling is data-driven.
    if 'rpc("getblocktemplate", [{"rules": []}]) or rpc("getblocktemplate", [])' not in t:
        raise RuntimeError("known-good getblocktemplate call missing")

    fixed_marker = 'MAX_DIFF = int(cfg["pool"].get("vardiff_max", 50_000_000))'
    if fixed_marker not in t:
        raise RuntimeError("vardiff_max pattern missing")
    t = t.replace(
        fixed_marker,
        fixed_marker + '\nFIXED_DIFF = int(cfg["pool"].get("fixed_difficulty", 13354))',
        1,
    )

    fixed_parser = '''def parse_fixed_diff(*candidates):
    """Explicit d=/diff= passwords select the configured FixedCoin difficulty."""
    for raw in candidates:
        if not raw or not isinstance(raw, str):
            continue
        m = re.search(r"(?:^|[;,\\s])(?:d|diff)\\s*[=:]\\s*(\\d+(?:\\.\\d+)?)", raw, re.I)
        if not m:
            m = re.match(r"^(?:d|diff)\\s*[=:]\\s*(\\d+(?:\\.\\d+)?)$", raw.strip(), re.I)
        if m:
            return FIXED_DIFF
    return None
'''
    t = replace_function(t, "parse_fixed_diff", fixed_parser)

    single = '''def build_coinbase_parts(height, miner_value_sats, miner_spk, dev_spk=None, en1_size=4, en2_size=4, witness_commitment_hex=None, *args, **kwargs):
    """Build a FixedCoin coinbase with the full subsidy to the payout address."""
    tag = b"/FIX-Solo/"
    height_script = bip34_height(height)
    scriptsig_len = len(height_script) + en1_size + en2_size + len(tag)
    part1 = struct.pack("<I", 2) + b"\\x01" + b"\\x00" * 32 + struct.pack("<I", 0xFFFFFFFF)
    part1 += encode_varint(scriptsig_len) + height_script

    witness_script = b""
    if witness_commitment_hex:
        try:
            witness_script = binascii.unhexlify(witness_commitment_hex)
        except Exception:
            witness_script = b""

    output_count = 2 if witness_script else 1
    part2 = tag + struct.pack("<I", 0xFFFFFFFF) + encode_varint(output_count)
    part2 += struct.pack("<Q", int(miner_value_sats))
    part2 += encode_varint(len(miner_spk)) + miner_spk
    if witness_script:
        part2 += struct.pack("<Q", 0)
        part2 += encode_varint(len(witness_script)) + witness_script
    part2 += struct.pack("<I", 0)
    return binascii.hexlify(part1).decode(), binascii.hexlify(part2).decode()
'''
    t = replace_function(t, "build_coinbase_parts", single)

    old_job = '"other_tx": other_tx, "created": time.time(),'
    new_job = (
        '"other_tx": other_tx, "created": time.time(),\n'
        '                "witness_commitment": tmpl.get("default_witness_commitment"),'
    )
    if old_job not in t:
        raise RuntimeError("job witness insertion point missing")
    t = t.replace(old_job, new_job, 1)

    old_call = '''build_coinbase_parts(
            job["height"], job["value"], job["spk"], job["dev_spk"],
            len(self.en1), self.en2_size,
        )'''
    new_call = '''build_coinbase_parts(
            job["height"], job["value"], job["spk"], job.get("dev_spk"),
            len(self.en1), self.en2_size,
            job.get("witness_commitment"),
        )'''
    if old_call in t:
        t = t.replace(old_call, new_call, 1)
    t = t.replace(
        'build_coinbase_parts(job["height"], job["value"], job["spk"], job["dev_spk"]',
        'build_coinbase_parts(job["height"], job["value"], job["spk"], job.get("dev_spk")',
    )

    witness_helper = '''def coinbase_add_witness(tx_nowitness: bytes, enabled: bool) -> bytes:
    """Serialize the BIP141 coinbase witness reserved value correctly."""
    if not enabled or len(tx_nowitness) < 8:
        return tx_nowitness
    if tx_nowitness[4:6] == b"\\x00\\x01":
        return tx_nowitness
    version = tx_nowitness[:4]
    body = tx_nowitness[4:-4]
    locktime = tx_nowitness[-4:]
    witness = b"\\x01\\x20" + (b"\\x00" * 32)
    return version + b"\\x00\\x01" + body + witness + locktime
'''
    if "def coinbase_add_witness" in t:
        t = replace_function(t, "coinbase_add_witness", witness_helper)
    else:
        t = t.replace("\ndef assemble_coinbase(", "\n" + witness_helper + "\ndef assemble_coinbase(", 1)

    old_block = "block = header + encode_varint(tx_count) + coinbase_tx"
    new_block = "block = header + encode_varint(tx_count) + coinbase_add_witness(coinbase_tx, bool(job.get(\"witness_commitment\")))"
    if old_block not in t:
        raise RuntimeError("submitblock insertion point missing")
    t = t.replace(old_block, new_block, 1)

    old_broadcast = "if job is not None and clean:\n                broadcast_job(clean=True)"
    new_broadcast = (
        "if job is not None:\n"
        "                if clean:\n"
        "                    broadcast_job(clean=True)\n"
        "                else:\n"
        "                    broadcast_job(clean=False)"
    )
    if old_broadcast in t:
        t = t.replace(old_broadcast, new_broadcast, 1)

    return t


def generate_server() -> None:
    print("Fetching known-good FreeCash stratum base…", flush=True)
    raw = urllib.request.urlopen(URL, timeout=60).read().decode()
    adapted = adapt(raw)
    ast.parse(adapted)
    assert "FIXED_DIFF" in adapted
    assert "witness_commitment" in adapted
    assert "coinbase_add_witness" in adapted
    FULL.write_text(f"# ADAPT_VERSION={ADAPT_VERSION}\n" + adapted)
    print("Wrote", FULL, FULL.stat().st_size, flush=True)


if os.environ.get("STRATUM_BUILD_ONLY") == "1":
    generate_server()
    raise SystemExit(0)

if not FULL.exists() or FULL.stat().st_size < 1000 or ADAPT_VERSION not in FULL.read_text(errors="ignore"):
    generate_server()

sys.argv[0] = str(FULL)
runpy.run_path(str(FULL), run_name="__main__")
