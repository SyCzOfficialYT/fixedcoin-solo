#!/usr/bin/env python3
"""Generate FixedCoin Stratum from the known-good FreeCash Stratum base."""
import ast, os, runpy, sys, urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
FULL = HERE / "server_full.py"
URL = "https://raw.githubusercontent.com/fixedcoin/freecash-coin/a88d89675b3a41cc6774e1b975e57e050d4892cc/stratum/server.py"
ADAPT_VERSION = "fixedcoin-fch-dashboard-repair-2026-08-20-v12"


def replace_function(source, name, replacement):
    tree = ast.parse(source)
    target = next((n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name), None)
    if target is None:
        raise RuntimeError(f"function {name!r} not found in FreeCash base")
    lines = source.splitlines(keepends=True)
    start = sum(map(len, lines[:target.lineno - 1]))
    end = sum(map(len, lines[:target.end_lineno]))
    return source[:start] + replacement.rstrip() + "\n" + source[end:]


def adapt(t):
    t = (t.replace('job_interval", 20)', 'job_interval", 30)')
         .replace('blog[-20:]', 'blog[-1000:]')
         .replace('+ 14400', '+ 100')
         .replace(' FCH', ' FIX')
         .replace('FreeCash', 'FixedCoin')
         .replace('/FCH-Solo/', '/FIX-Solo/'))

    for old in (
        'rpc("getblocktemplate", [{"rules": []}]) or rpc("getblocktemplate", [])',
        'rpc("getblocktemplate", [{"rules": []}])',
        'rpc("getblocktemplate", [])',
    ):
        if old in t:
            t = t.replace(old, 'rpc("getblocktemplate", [{"rules": ["segwit"]}])', 1)
            break
    if 'rpc("getblocktemplate", [{"rules": ["segwit"]}])' not in t:
        raise RuntimeError("segwit GBT patch failed")

    rpc_func = '''def rpc(method, params=None):
    try:
        r = requests.post(
            f"http://{RPC_HOST}:{RPC_PORT}",
            json={"jsonrpc": "1.0", "id": "fch-stratum", "method": method, "params": params or []},
            auth=HTTPBasicAuth(RPC_USER, RPC_PASS), timeout=60,
        )
        try:
            data = r.json()
        except Exception:
            data = None
        if r.status_code != 200:
            detail = data.get("error") if isinstance(data, dict) else r.text[:500]
            emit("ERROR", f"RPC {method}: HTTP {r.status_code}: {detail}")
            return None
        if isinstance(data, dict) and data.get("error"):
            emit("ERROR", f"RPC {method}: {data['error']}")
            return None
        return data.get("result") if isinstance(data, dict) else None
    except Exception as e:
        emit("ERROR", f"RPC {method}: {e}")
        return None
'''
    t = replace_function(t, 'rpc', rpc_func)

    submit_verified = '''def submitblock_verified(block_hex, expected_hash, expected_height):
    """Submit a candidate and verify it is actually present in the node chain.

    JSON-RPC submitblock returns null/empty on success, so the generic rpc()
    helper cannot distinguish that from an RPC failure. Never emit BLOCK
    ACCEPTED merely because the RPC wrapper returned None: query the node for
    the exact candidate hash and require the expected height.
    """
    try:
        r = requests.post(
            f"http://{RPC_HOST}:{RPC_PORT}",
            json={"jsonrpc": "1.0", "id": "submitblock", "method": "submitblock", "params": [block_hex]},
            auth=HTTPBasicAuth(RPC_USER, RPC_PASS), timeout=120,
        )
        try:
            data = r.json()
        except Exception:
            data = None
        if r.status_code != 200:
            detail = data.get("error") if isinstance(data, dict) else r.text[:500]
            return False, f"HTTP {r.status_code}: {detail}"
        if isinstance(data, dict) and data.get("error"):
            return False, str(data["error"])
        result = data.get("result") if isinstance(data, dict) else None
        if result not in (None, ""):
            return False, str(result)

        # A successful submit must be observable in the node. This also
        # protects against stale/side-chain candidates that are not the active tip.
        for _ in range(10):
            block = rpc("getblock", [expected_hash, 1])
            if block and int(block.get("height", -1)) == int(expected_height):
                return True, None
            time.sleep(0.5)
        return False, "submitblock returned success but candidate was not found at expected height"
    except Exception as e:
        return False, str(e)
'''
    if 'def submitblock_verified(' not in t:
        t = t.replace('\ndef sha256d(', '\n' + submit_verified + '\ndef sha256d(', 1)

    old_submit = 'res = rpc("submitblock", [binascii.hexlify(block).decode()])\n            if res in (None, ""):'
    new_submit = 'accepted, submit_error = submitblock_verified(\n                binascii.hexlify(block).decode(), hhex, job["height"]\n            )\n            if accepted:'
    if old_submit not in t:
        raise RuntimeError('unsafe submitblock handling not found')
    t = t.replace(old_submit, new_submit, 1)
    t = t.replace('emit("ERROR", f"submitblock rejected: {res}")', 'emit("ERROR", f"submitblock rejected/unverified: {submit_error}")', 1)

    marker = 'MAX_DIFF = int(cfg["pool"].get("vardiff_max", 50_000_000))'
    if marker not in t:
        raise RuntimeError('vardiff marker missing')
    if 'FIXED_DIFF = int(cfg["pool"].get("fixed_difficulty", 13354))' not in t:
        t = t.replace(marker, marker + '\nFIXED_DIFF = int(cfg["pool"].get("fixed_difficulty", 13354))', 1)

    fixed_parser = '''def parse_fixed_diff(*candidates):
    for raw in candidates:
        if not raw or not isinstance(raw, str):
            continue
        m = re.search(r"(?:^|[;,\\s])(?:d|diff)\\s*[=:]\\s*(\\d+(?:\\.\\d+)?)", raw, re.I)
        if not m:
            m = re.match(r"^(?:d|diff)\\s*[=:]\\s*(\\d+(?:\\.\\d+)?)$", raw.strip(), re.I)
        if m:
            try:
                return FIXED_DIFF
            except Exception:
                pass
    return None
'''
    t = replace_function(t, 'parse_fixed_diff', fixed_parser)

    coinbase = '''def build_coinbase_parts(height, miner_value_sats, miner_spk, dev_spk=None, en1_size=4, en2_size=4, witness_commitment_hex=None, *args, **kwargs):
    tag = b"/FIX-Solo/"
    height_script = bip34_height(height)
    scriptsig_len = len(height_script) + en1_size + en2_size + len(tag)
    part1 = struct.pack("<I", 2) + b"\\x01" + b"\\x00" * 32 + struct.pack("<I", 0xFFFFFFFF) + encode_varint(scriptsig_len) + height_script
    witness = b""
    if witness_commitment_hex:
        try:
            witness = binascii.unhexlify(witness_commitment_hex)
        except Exception:
            witness = b""
    outputs = 2 if witness else 1
    part2 = tag + struct.pack("<I", 0xFFFFFFFF) + encode_varint(outputs) + struct.pack("<Q", int(miner_value_sats)) + encode_varint(len(miner_spk)) + miner_spk
    if witness:
        part2 += struct.pack("<Q", 0) + encode_varint(len(witness)) + witness
    part2 += struct.pack("<I", 0)
    return binascii.hexlify(part1).decode(), binascii.hexlify(part2).decode()
'''
    t = replace_function(t, 'build_coinbase_parts', coinbase)

    old = '"other_tx": other_tx, "created": time.time(),'
    if old in t and '"witness_commitment": tmpl.get("default_witness_commitment")' not in t:
        t = t.replace(old, old + '\n                "witness_commitment": tmpl.get("default_witness_commitment"),', 1)

    oldcall = '''build_coinbase_parts(
            job["height"], job["value"], job["spk"], job["dev_spk"],
            len(self.en1), self.en2_size,
        )'''
    newcall = '''build_coinbase_parts(
            job["height"], job["value"], job.get("spk"), job.get("dev_spk"),
            len(self.en1), self.en2_size, job.get("witness_commitment"),
        )'''
    if oldcall in t:
        t = t.replace(oldcall, newcall, 1)
    t = t.replace('build_coinbase_parts(job["height"], job["value"], job["spk"], job["dev_spk"]', 'build_coinbase_parts(job["height"], job["value"], job.get("spk"), job.get("dev_spk")', 1)

    witness = '''def coinbase_add_witness(tx_nowitness, enabled):
    if not enabled or len(tx_nowitness) < 8 or tx_nowitness[4:6] == b"\\x00\\x01":
        return tx_nowitness
    return tx_nowitness[:4] + b"\\x00\\x01" + tx_nowitness[4:-4] + b"\\x01\\x20" + (b"\\x00" * 32) + tx_nowitness[-4:]
'''
    if 'def coinbase_add_witness' in t:
        t = replace_function(t, 'coinbase_add_witness', witness)
    else:
        t = t.replace('\ndef assemble_coinbase(', '\n' + witness + '\ndef assemble_coinbase(', 1)

    oldblock = 'block = header + encode_varint(tx_count) + coinbase_tx'
    newblock = 'block = header + encode_varint(tx_count) + coinbase_add_witness(coinbase_tx, bool(job.get("witness_commitment")))'
    if oldblock in t:
        t = t.replace(oldblock, newblock, 1)

    oldaddr = '''    info2 = rpc("getaddressinfo", [addr])
    if info2 and info2.get("scriptPubKey"):
        return binascii.unhexlify(info2["scriptPubKey"])
'''
    t = t.replace(oldaddr, '')
    t = t.replace('"mature_at_height": job["height"] + 14400,', '"mature_at_height": job["height"] + 100,', 1)
    return t


def generate_server():
    print("Fetching known-good FreeCash Stratum base…", flush=True)
    raw = urllib.request.urlopen(URL, timeout=60).read().decode()
    adapted = adapt(raw)
    ast.parse(adapted)
    assert 'rpc("getblocktemplate", [{"rules": ["segwit"]}])' in adapted
    assert 'rpc("getblocktemplate", [{"rules": []}])' not in adapted
    assert 'submitblock_verified(' in adapted
    assert 'if res in (None, ""):' not in adapted
    FULL.write_text(f"# ADAPT_VERSION={ADAPT_VERSION}\n" + adapted)
    print("Wrote", FULL, FULL.stat().st_size, flush=True)


if os.environ.get('STRATUM_BUILD_ONLY') == '1':
    generate_server()
    raise SystemExit(0)

if not FULL.exists() or ADAPT_VERSION not in FULL.read_text(errors='ignore'):
    generate_server()

sys.argv[0] = str(FULL)
runpy.run_path(str(FULL), run_name='__main__')
