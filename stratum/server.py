#!/usr/bin/env python3
"""Build the FixedCoin stratum from the known-good FreeCash base, locally."""
import ast
import os
import re
import runpy
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
FULL = HERE / "server_full.py"
URL = "https://raw.githubusercontent.com/SyCzOfficialYT/freecash-coin/a88d89675b3a41cc6774e1b975e57e050d4892cc/stratum/server.py"
ADAPT_VERSION = "fixedcoin-fch-dashboard-repair-2026-08-14-v3-segwit"


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
    fixed_parser = '''def parse_fixed_diff(*candidates):
    """Explicit d=/diff= passwords select the configured FixedCoin difficulty."""
    for raw in candidates:
        if not raw or not isinstance(raw, str):
            continue
        if re.search(r"(?:^|[;,\\s])(?:d|diff)\\s*[=:]\\s*\\d+(?:\\.\\d+)?", raw, re.I):
            return FIXED_DIFF
    return None

'''
    t = t[:start_fixed] + fixed_parser + t[end_fixed:]

    # Remove the FreeCash governance/dev output. FixedCoin pays the configured
    # holding address only; the block subsidy remains the miner's full value.
    t = "\n".join(
        line for line in t.splitlines()
        if "DEV_ADDRESS" not in line and "dev_spk" not in line
    ) + "\n"

    # FixedCoin coinbase: one miner output plus the optional BIP141 witness
    # commitment output supplied by getblocktemplate.
    start = t.find("def build_coinbase_parts(")
    if start < 0:
        raise RuntimeError("build_coinbase_parts not found")
    rest = t[start:]
    m = re.search(r"\ndef [a-zA-Z_]", rest[1:])
    if not m:
        raise RuntimeError("end of build_coinbase_parts not found")
    end = start + 1 + m.start()
    single = '''def build_coinbase_parts(height, miner_value_sats, miner_spk, en1_size=4, en2_size=4, witness_commitment_hex=None, *args, **kwargs):
    """Single miner output + optional BIP141 witness commitment."""
    tag = b"/FIX-Solo/"
    height_script = bip34_height(height)
    scriptsig_len = len(height_script) + en1_size + en2_size + len(tag)
    part1 = struct.pack("<I", 2) + b"\\x01" + b"\\x00" * 32 + struct.pack("<I", 0xFFFFFFFF)
    part1 += encode_varint(scriptsig_len) + height_script

    wscript = b""
    if witness_commitment_hex:
        try:
            wscript = binascii.unhexlify(witness_commitment_hex)
        except Exception:
            wscript = b""

    n_out = 2 if wscript else 1
    part2 = tag + struct.pack("<I", 0xFFFFFFFF) + encode_varint(n_out)
    part2 += struct.pack("<Q", int(miner_value_sats))
    part2 += encode_varint(len(miner_spk)) + miner_spk
    if wscript:
        part2 += struct.pack("<Q", 0)
        part2 += encode_varint(len(wscript)) + wscript
    part2 += struct.pack("<I", 0)
    return binascii.hexlify(part1).decode(), binascii.hexlify(part2).decode()


def coinbase_add_witness(tx_nowitness: bytes) -> bytes:
    """Add the BIP141 coinbase witness reserved value to the serialized tx."""
    if len(tx_nowitness) < 10:
        return tx_nowitness
    version, rest = tx_nowitness[:4], tx_nowitness[4:]
    if len(rest) >= 2 and rest[0] == 0 and rest[1] == 1:
        return tx_nowitness
    witness = b"\\x01\\x20" + (b"\\x00" * 32)
    return version + b"\\x00\\x01" + rest + witness

'''
    t = t[:start] + single + t[end:]

    # Adapt all coinbase call sites to the FixedCoin single-output builder and
    # pass the template witness commitment when available.
    t = t.replace(
        '''build_coinbase_parts(\n            job["height"], job["value"], job["spk"], job["dev_spk"],\n            len(self.en1), self.en2_size,\n        )''',
        '''build_coinbase_parts(\n            job["height"], job["value"], job["spk"],\n            len(self.en1), self.en2_size,\n            job.get("witness_commitment"),\n        )''',
    )
    t = t.replace(
        'build_coinbase_parts(job["height"], job["value"], job["spk"], job["dev_spk"]',
        'build_coinbase_parts(job["height"], job["value"], job["spk"]',
    )

    old_job = '"other_tx": other_tx, "created": time.time(),'
    new_job = (
        '"other_tx": other_tx, "created": time.time(),\n'
        '                "witness_commitment": tmpl.get("default_witness_commitment"),'
    )
    if old_job not in t:
        raise RuntimeError("job witness insertion point missing")
    t = t.replace(old_job, new_job, 1)

    old_block = "block = header + encode_varint(tx_count) + coinbase_tx"
    new_block = "block = header + encode_varint(tx_count) + coinbase_add_witness(coinbase_tx)"
    if old_block not in t:
        raise RuntimeError("submitblock insertion point missing")
    t = t.replace(old_block, new_block, 1)

    # Always broadcast refreshes; clean jobs are still marked clean.
    old = "if job is not None and clean:\n                broadcast_job(clean=True)"
    new = (
        "if job is not None:\n"
        "                if clean:\n"
        "                    broadcast_job(clean=True)\n"
        "                else:\n"
        "                    broadcast_job(clean=False)"
    )
    if old in t:
        t = t.replace(old, new, 1)

    return t


def generate_server() -> None:
    print("Fetching known-good FreeCash stratum base…", flush=True)
    raw = urllib.request.urlopen(URL, timeout=60).read().decode()
    adapted = adapt(raw)
    ast.parse(adapted)
    assert "DEV_ADDRESS" not in adapted
    assert "dev_spk" not in adapted
    assert '"segwit"' in adapted
    assert "FIXED_DIFF" in adapted
    assert "witness_commitment" in adapted
    assert "coinbase_add_witness" in adapted
    assert 'job["dev_spk"]' not in adapted
    FULL.write_text(f"# ADAPT_VERSION={ADAPT_VERSION}\n" + adapted)
    print("Wrote", FULL, FULL.stat().st_size, flush=True)


if os.environ.get("STRATUM_BUILD_ONLY") == "1":
    generate_server()
    raise SystemExit(0)

if not FULL.exists() or FULL.stat().st_size < 1000 or ADAPT_VERSION not in FULL.read_text(errors="ignore"):
    generate_server()

sys.argv[0] = str(FULL)
runpy.run_path(str(FULL), run_name="__main__")
