#!/bin/bash
# FixedCoin Solo – fixedcoind + stratum + dashboard, config.yaml auto
set -u

DATADIR="${FIX_DATADIR:-/data/fixedcoin}"
RPCUSER="${FIX_RPCUSER:-fixrpc}"
RPCPASS="${FIX_RPCPASS:-FixedcoinSoloAutoRpc_ChangeMeIfPublic}"
RPCPORT="${FIX_RPCPORT:-24761}"
P2PPORT="${FIX_P2PPORT:-24768}"
DASH_PORT="${FIX_DASH_PORT:-5050}"

mkdir -p "$DATADIR" /data /app/data /app/logs /app/config
cd /app

echo "[allinone] FixedCoin Solo boot"

# --- fixedcoin.conf ---
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

# --- config.yaml always (like FreeCash) ---
python3 - <<'PY' || true
import yaml, os
from pathlib import Path
p = Path("/app/config/config.yaml")
cfg = {}
if p.exists():
    try:
        cfg = yaml.safe_load(p.read_text()) or {}
    except Exception:
        cfg = {}
cfg.setdefault("rpc", {})
cfg["rpc"].update({
    "host": "127.0.0.1",
    "port": int(os.environ.get("FIX_RPCPORT", "24761")),
    "user": os.environ.get("FIX_RPCUSER", "fixrpc"),
    "password": os.environ.get("FIX_RPCPASS", "FixedcoinSoloAutoRpc_ChangeMeIfPublic"),
    "timeout": 30,
})
cfg.setdefault("pool", {})
cfg["pool"].setdefault("payout_address", "fix1CHANGE_ME_GETNEWADDRESS")
cfg["pool"].setdefault("stratum_port", 3333)
cfg["pool"].setdefault("stratum_host", "0.0.0.0")
cfg["pool"].setdefault("start_difficulty", 10000)
cfg["pool"].setdefault("min_difficulty", 1000)
cfg["pool"].setdefault("job_interval", 30)
cfg["monitor"] = {"host": "0.0.0.0", "port": int(os.environ.get("FIX_DASH_PORT", "5050"))}
cfg.setdefault("logging", {"level": "INFO"})
p.write_text(yaml.safe_dump(cfg, default_flow_style=False, sort_keys=False))
print("[allinone] config.yaml ready, monitor", cfg["monitor"]["port"])
PY

# --- CLI wrapper ---
if [ -x /usr/local/bin/fixedcoin-cli ] && [ ! -f /usr/local/bin/fixedcoin-cli.real ]; then
  mv /usr/local/bin/fixedcoin-cli /usr/local/bin/fixedcoin-cli.real
fi
cat > /usr/local/bin/fixedcoin-cli << EOF
#!/bin/bash
exec /usr/local/bin/fixedcoin-cli.real -datadir="$DATADIR" -rpcuser="$RPCUSER" -rpcpassword="$RPCPASS" "\$@"
EOF
chmod +x /usr/local/bin/fixedcoin-cli
export PATH="/usr/local/bin:$PATH"

echo "[allinone] start fixedcoind"
fixedcoind -datadir="$DATADIR" -conf="$DATADIR/fixedcoin.conf" &
NODE_PID=$!

for i in $(seq 1 180); do
  if fixedcoin-cli getblockchaininfo >/dev/null 2>&1; then
    echo "[allinone] RPC ok (${i}s)"
    break
  fi
  if ! kill -0 $NODE_PID 2>/dev/null; then
    echo "[allinone] fixedcoind died"
    exit 1
  fi
  sleep 1
done

# Wallet + payout address auto
python3 /app/scripts/setup_address.py 2>/dev/null || echo "[allinone] address setup skip/later"
touch /data/events.jsonl /data/stats.json /app/data/events.jsonl /app/data/stratum.log /app/data/dashboard.log 2>/dev/null || true

# keep stratum + dashboard alive
run_forever() {
  local name="$1"
  local logfile="$2"
  shift 2
  while true; do
    echo "[allinone] start $name: $*"
    "$@" >>"$logfile" 2>&1 &
    local pid=$!
    echo $pid >"/tmp/${name}.pid"
    wait $pid
    local rc=$?
    echo "[allinone] $name exited rc=$rc – restart in 3s"
    sleep 3
  done
}

run_forever stratum /app/data/stratum.log python3 /app/stratum/server.py &
run_forever dashboard /app/data/dashboard.log python3 /app/monitor/app.py &

sleep 3
ADDR=$(python3 -c "import yaml;print(yaml.safe_load(open('/app/config/config.yaml')).get('pool',{}).get('payout_address','?'))" 2>/dev/null || echo "?")
echo "[allinone] ========================================"
echo "[allinone] Dashboard  http://0.0.0.0:${DASH_PORT}"
echo "[allinone] Stratum    :3333"
echo "[allinone] Holding    $ADDR"
echo "[allinone] ========================================"

wait $NODE_PID
