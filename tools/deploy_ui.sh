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

# 1) Replace coinbase WHILE original def still present
start = t.find("def build_coinbase_parts(")
if start < 0:
    raise SystemExit("build_coinbase_parts not found")
rest = t[start:]
m = re.search(r"\ndef [a-zA-Z_]", rest[1:])
if not m:
    raise SystemExit("end of build_coinbase_parts not found")
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

# 2) Drop DEV / dual-output leftovers
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
assert "blog[-1000:]" in t
p.write_text(t)
print("server OK (FIX single-out)")
PY

printf '%s\n' "==> Prepare monitor app"
cp -f monitor/app.py "$TMP_DIR/app.py"
sed -i 's/list(reversed(mat))\[:10\]/list(reversed(mat))[:1000]/' "$TMP_DIR/app.py" 2>/dev/null || true
sed -i 's/list(reversed(mat))\[:20\]/list(reversed(mat))[:1000]/' "$TMP_DIR/app.py" 2>/dev/null || true

printf '%s\n' "==> Check dashboard"
test -f monitor/templates/dashboard.html
grep -E "Live Competition|/api/logs|terminal" monitor/templates/dashboard.html >/dev/null

printf '%s\n' "==> Copy into $CONTAINER"
sudo docker cp "$TMP_DIR/server.py" "$CONTAINER:/app/stratum/server.py"
sudo docker cp "$TMP_DIR/app.py" "$CONTAINER:/app/monitor/app.py"
sudo docker cp monitor/templates/dashboard.html "$CONTAINER:/app/monitor/templates/dashboard.html"
sudo docker exec "$CONTAINER" mkdir -p /app/tools
if [ -f tools/rebuild_blocks_log.py ]; then
  sudo docker cp tools/rebuild_blocks_log.py "$CONTAINER:/app/tools/rebuild_blocks_log.py"
fi
sudo docker exec "$CONTAINER" rm -f /app/stratum/server_full.py 2>/dev/null || true

printf '%s\n' "==> Rebuild blocks_log (wallet only)"
sudo docker exec "$CONTAINER" python3 /app/tools/rebuild_blocks_log.py 2>/dev/null || true

printf '%s\n' "==> Restart"
sudo docker restart "$CONTAINER"
sleep 8
echo "==> Logs (last 40)"
sudo docker logs "$CONTAINER" --tail 40 2>&1 | tail -40
echo "Done. Ctrl+F5."
