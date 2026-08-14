#!/bin/sh
# Deploy FixedCoin solo UI + stratum (does not dirty tracked sources)
set -e
cd "$(dirname "$0")/.."

CONTAINER="${FIX_CONTAINER:-fixedcoin-solo}"
TMP_DIR="${TMPDIR:-/tmp}/fixedcoin-solo-deploy"
mkdir -p "$TMP_DIR"
trap 'rm -rf "$TMP_DIR"' EXIT

printf '%s\n' "==> Fetch FreeCash server base (a88d) and adapt for FIX"
curl -fsSL "https://raw.githubusercontent.com/SyCzOfficialYT/freecash-coin/a88d89675b/stratum/server.py" -o "$TMP_DIR/server.py"

python3 - "$TMP_DIR/server.py" <<'PY'
import ast, re, sys
from pathlib import Path

p = Path(sys.argv[1])
t = p.read_text()

t = t.replace('job_interval", 20)', 'job_interval", 30)')
t = t.replace("blog[-20:]", "blog[-1000:]")
t = t.replace("+ 14400", "+ 100")
t = t.replace(" FCH", " FIX")
t = t.replace("FreeCash", "FixedCoin")
t = t.replace("/FCH-Solo/", "/FIX-Solo/")

old_gbt = 'rpc("getblocktemplate", [{"rules": []}]) or rpc("getblocktemplate", [])'
new_gbt = 'rpc("getblocktemplate", [{"rules": ["segwit"]}])'
if old_gbt not in t:
    raise SystemExit("getblocktemplate call pattern not found")
t = t.replace(old_gbt, new_gbt)
print("gbt segwit OK")

# Call sites: drop dev_spk arg BEFORE stripping lines
for a, b in [
    (
        'build_coinbase_parts(\n            job["height"], job["value"], job["spk"], job["dev_spk"],\n            len(self.en1), self.en2_size,\n        )',
        'build_coinbase_parts(\n            job["height"], job["value"], job["spk"],\n            len(self.en1), self.en2_size,\n            job.get("witness_commitment"),\n        )',
    ),
    (
        'build_coinbase_parts(\n            job["height"], job["value"], job["spk"], job["dev_spk"],',
        'build_coinbase_parts(\n            job["height"], job["value"], job["spk"],',
    ),
]:
    if a in t:
        t = t.replace(a, b)
        print("call site patched")

# Store witness commitment on job dict
old_job = '"other_tx": other_tx, "created": time.time(),'
new_job = (
    '"other_tx": other_tx, "created": time.time(),\n'
    '                "witness_commitment": tmpl.get("default_witness_commitment"),'
)
if old_job in t:
    t = t.replace(old_job, new_job, 1)
    print("job witness_commitment field OK")

start = t.find("def build_coinbase_parts(")
if start < 0:
    raise SystemExit("build_coinbase_parts not found")
rest = t[start:]
m = re.search(r"\ndef [a-zA-Z_]", rest[1:])
if not m:
    raise SystemExit("end of build_coinbase_parts not found")
end = start + 1 + m.start()

single = r'''def build_coinbase_parts(height, miner_value_sats, miner_spk, en1_size=4, en2_size=4, witness_commitment_hex=None, *args, **kwargs):
    """Single miner output + optional segwit witness commitment (FixedCoin)."""
    tag = b"/FIX-Solo/"
    height_script = bip34_height(height)
    scriptsig_len = len(height_script) + en1_size + en2_size + len(tag)
    part1 = struct.pack("<I", 2) + b"\x01" + b"\x00" * 32 + struct.pack("<I", 0xFFFFFFFF)
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
    """BIP141: version|00|01|vin+vout+locktime|coinbase-witness(32 zero bytes)."""
    if len(tx_nowitness) < 10:
        return tx_nowitness
    version, rest = tx_nowitness[:4], tx_nowitness[4:]
    # already witness?
    if len(rest) >= 2 and rest[0] == 0 and rest[1] == 1:
        return tx_nowitness
    witness = b"\x01\x20" + (b"\x00" * 32)
    return version + b"\x00\x01" + rest + witness

'''
t = t[:start] + single + t[end:]

# Block assembly must use witness-serialized coinbase for submitblock
old_block = "block = header + encode_varint(tx_count) + coinbase_tx"
new_block = "block = header + encode_varint(tx_count) + coinbase_add_witness(coinbase_tx)"
if old_block in t:
    t = t.replace(old_block, new_block, 1)
    print("submitblock witness OK")

# Drop DEV / dual-output leftovers
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
    print("job_loop patched")

ast.parse(t)
assert "DEV_ADDRESS" not in t
assert "dev_spk" not in t
assert '"segwit"' in t
assert "witness_commitment" in t
assert "coinbase_add_witness" in t
assert "blog[-1000:]" in t
p.write_text(t)
print("server OK (FIX segwit coinbase + GBT)")
PY

printf '%s\n' "==> Prepare monitor app"
cp -f monitor/app.py "$TMP_DIR/app.py"

printf '%s\n' "==> Check dashboard"
test -f monitor/templates/dashboard.html || python3 tools/patch_dashboard.py
if [ -f tools/patch_timebar.py ]; then
  python3 tools/patch_timebar.py monitor/templates/dashboard.html || true
fi
grep -E "Live Competition|heightStrip" monitor/templates/dashboard.html >/dev/null

printf '%s\n' "==> Copy into $CONTAINER"
sudo docker cp "$TMP_DIR/server.py" "$CONTAINER:/app/stratum/server.py"
sudo docker cp "$TMP_DIR/app.py" "$CONTAINER:/app/monitor/app.py"
sudo docker cp monitor/templates/dashboard.html "$CONTAINER:/app/monitor/templates/dashboard.html"
sudo docker exec "$CONTAINER" mkdir -p /app/tools
if [ -f tools/rebuild_blocks_log.py ]; then
  sudo docker cp tools/rebuild_blocks_log.py "$CONTAINER:/app/tools/rebuild_blocks_log.py"
fi
sudo docker exec "$CONTAINER" rm -f /app/stratum/server_full.py 2>/dev/null || true

# Prefer stratum-only restart so node keeps running
if sudo docker exec "$CONTAINER" test -f /tmp/stratum.pid; then
  echo "==> Restart stratum only"
  sudo docker exec "$CONTAINER" sh -c 'kill $(cat /tmp/stratum.pid) 2>/dev/null || true'
  sleep 4
else
  echo "==> Full restart"
  sudo docker restart "$CONTAINER"
  sleep 10
  sudo docker exec "$CONTAINER" fixedcoin-cli loadwallet mining 2>/dev/null || true
fi

echo "==> Stratum tail"
sudo docker exec "$CONTAINER" tail -30 /app/data/stratum.log 2>/dev/null || true
echo "Done. Ctrl+F5."
