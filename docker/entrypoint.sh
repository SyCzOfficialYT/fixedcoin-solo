#!/bin/bash
# FixedCoin Solo – fixedcoind + stratum + dashboard, persistent wallet/payout config
set -u

DATADIR="${FIX_DATADIR:-/data/fixedcoin}"
RPCUSER="${FIX_RPCUSER:-fixrpc}"
RPCPASS="${FIX_RPCPASS:-FixedcoinSoloAutoRpc_ChangeMeIfPublic}"
RPCPORT="${FIX_RPCPORT:-24761}"
P2PPORT="${FIX_P2PPORT:-24768}"
DASH_PORT="${FIX_DASH_PORT:-5050}"

mkdir -p "$DATADIR" /data /app/data /app/logs /app/config
cd /app

# Payout address is state, not image configuration. Prefer an explicit env
# override; otherwise restore the address generated during the first boot.
PAYOUT_FILE="$DATADIR/payout_address"
PAYOUT_ADDRESS="${FIX_PAYOUT_ADDRESS:-}"
if [ -z "$PAYOUT_ADDRESS" ] && [ -s "$PAYOUT_FILE" ]; then
    PAYOUT_ADDRESS="$(tr -d '\r\n ' < "$PAYOUT_FILE")"
fi

# Keep the daemon config deterministic while allowing the persistent wallet
# and payout address to survive container/image recreation.
cat > "$DATADIR/fixedcoin.conf" << EOF
server=1
daemon=0
listen=1
port=${P2PPORT}
rpcport=${RPCPORT}
rpcuser=${RPCUSER}
rpcpassword=${RPCPASS}
rpcallowip=127.0.0.1
txindex=1
printtoconsole=1
addnode=node1.fixedcoin.org
addnode=node2.fixedcoin.org
EOF

python3 - <<'PY' || true
import yaml, os
from pathlib import Path
p = Path("/app/config/config.yaml")
cfg = {}
if p.exists():
    try: cfg = yaml.safe_load(p.read_text()) or {}
    except Exception: cfg = {}
cfg.setdefault("rpc", {})
cfg["rpc"].update({
    "host": "127.0.0.1",
    "port": int(os.environ.get("FIX_RPCPORT", "24761")),
    "user": os.environ.get("FIX_RPCUSER", "fixrpc"),
    "password": os.environ.get("FIX_RPCPASS") or "FixedcoinSoloAutoRpc_ChangeMeIfPublic",
    "timeout": 30,
})
cfg.setdefault("pool", {})
payout = (os.environ.get("FIX_PAYOUT_ADDRESS") or "").strip()
if not payout:
    payout_file = Path(os.environ.get("FIX_DATADIR", "/data/fixedcoin")) / "payout_address"
    if payout_file.exists():
        payout = payout_file.read_text().strip()
if payout:
    cfg["pool"]["payout_address"] = payout
else:
    cfg["pool"].setdefault("payout_address", "fix1CHANGE_ME_GETNEWADDRESS")
cfg["pool"]["stratum_port"] = int(cfg["pool"].get("stratum_port", 3333))
cfg["pool"]["stratum_host"] = cfg["pool"].get("stratum_host", "0.0.0.0")
cfg["pool"]["start_difficulty"] = int(cfg["pool"].get("start_difficulty", 10000))
cfg["pool"]["fixed_difficulty"] = int(cfg["pool"].get("fixed_difficulty", 13354))
cfg["pool"]["min_difficulty"] = int(cfg["pool"].get("min_difficulty", 1000))
cfg["pool"]["job_interval"] = int(cfg["pool"].get("job_interval", 30))
cfg["monitor"] = {"host": "0.0.0.0", "port": int(os.environ.get("FIX_DASH_PORT", "5050"))}
cfg.setdefault("logging", {"level": "INFO"})
p.write_text(yaml.safe_dump(cfg, default_flow_style=False, sort_keys=False))
print("[allinone] config.yaml ready, payout", cfg["pool"].get("payout_address"), "monitor", cfg["monitor"]["port"])
PY

if [ -x /usr/local/bin/fixedcoin-cli ] && [ ! -f /usr/local/bin/fixedcoin-cli.real ]; then
    mv /usr/local/bin/fixedcoin-cli /usr/local/bin/fixedcoin-cli.real
fi
cat > /usr/local/bin/fixedcoin-cli << EOF
#!/bin/bash
exec /usr/local/bin/fixedcoin-cli.real -datadir="$DATADIR" -rpcuser="$RPCUSER" -rpcpassword="$RPCPASS" "\$@"
EOF
chmod +x /usr/local/bin/fixedcoin-cli
export PATH="/usr/local/bin:$PATH"
touch /data/events.jsonl /data/stats.json /app/data/events.jsonl /app/data/stratum.log /app/data/dashboard.log 2>/dev/null || true

python3 - <<'PY'
from pathlib import Path
from monitor.app import app
p = Path('/app/monitor/templates/dashboard.html')
assert p.exists() and p.stat().st_size == 17311, f'dashboard.html mismatch: {p.stat().st_size if p.exists() else "missing"}'
assert any(r.rule == '/' for r in app.url_map.iter_rules()), 'Flask dashboard route / is missing'
print('[allinone] dashboard verification PASS: exact NEW-FCH template + / route')
PY

run_forever() { local name="$1"; local logfile="$2"; shift 2; while true; do echo "[allinone] start $name: $*"; "$@" >>"$logfile" 2>&1 & local pid=$!; echo $pid >"/tmp/${name}.pid"; wait $pid; local rc=$?; echo "[allinone] $name exited rc=$rc – restart in 3s"; sleep 3; done; }

run_forever dashboard /app/data/dashboard.log python3 /app/monitor/app.py &
DASH_SUPERVISOR_PID=$!
echo "[allinone] dashboard supervisor started on :${DASH_PORT}"

echo "[allinone] start fixedcoind"
fixedcoind -datadir="$DATADIR" -conf="$DATADIR/fixedcoin.conf" &
NODE_PID=$!

for i in $(seq 1 180); do
  if fixedcoin-cli getblockchaininfo >/dev/null 2>&1; then echo "[allinone] RPC ok (${i}s)"; break; fi
  if ! kill -0 $NODE_PID 2>/dev/null; then echo "[allinone] fixedcoind died"; exit 1; fi
  if [ "$i" -eq 180 ]; then echo "[allinone] RPC timeout"; exit 1; fi
  sleep 1
done

echo "[allinone] verify chain + RPC"
if FIX_RPC_HOST=127.0.0.1 FIX_RPC_PORT="$RPCPORT" FIX_RPCUSER="$RPCUSER" FIX_RPCPASS="$RPCPASS" FIX_RPC_IN_CONTAINER=1 python3 /app/tools/verify_chain_rpc.py; then
    echo "[allinone] chain/RPC verification PASS"
else
    echo "[allinone] WARNING: chain/RPC verification FAILED; keeping container alive and starting stratum anyway"
fi

python3 /app/scripts/setup_address.py 2>/dev/null || echo "[allinone] address setup skip/later"

# The Stratum adapter is generated from an upstream base at build/runtime.
# Always apply the deterministic FixedCoin difficulty patch immediately before
# starting it, so a regenerated adapter cannot silently reintroduce the wrong
# Bitcoin Diff1 share-work formula.
if python3 /app/scripts/fixcoin_stratum_difficulty_patch.py; then
    echo "[allinone] Stratum difficulty verification PASS"
else
    echo "[allinone] FATAL: Stratum difficulty verification failed"
    exit 1
fi

run_forever stratum /app/data/stratum.log python3 /app/stratum/server.py &
STRATUM_SUPERVISOR_PID=$!

sleep 3
ADDR=$(python3 -c "import yaml;print(yaml.safe_load(open('/app/config/config.yaml')).get('pool',{}).get('payout_address','?'))" 2>/dev/null || echo "?")
echo "[allinone] ========================================"
echo "[allinone] Dashboard  http://0.0.0.0:${DASH_PORT}"
echo "[allinone] Stratum    :3333"
echo "[allinone] Holding    $ADDR"
echo "[allinone] ========================================"

wait $NODE_PID
