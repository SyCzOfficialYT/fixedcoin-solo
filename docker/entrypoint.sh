#!/bin/bash
set -e
DATADIR="${FIX_DATADIR:-/data/fixedcoin}"
mkdir -p "$DATADIR" /data /app/data

CONF="$DATADIR/fixedcoin.conf"
if [ ! -f "$CONF" ]; then
  RPC_USER=$(python3 -c "import yaml; print(yaml.safe_load(open('/app/config/config.yaml'))['rpc']['user'])")
  RPC_PASS=$(python3 -c "import yaml; print(yaml.safe_load(open('/app/config/config.yaml'))['rpc']['password'])")
  cat > "$CONF" <<EOF
server=1
daemon=0
txindex=1
listen=1
port=24768
rpcuser=$RPC_USER
rpcpassword=$RPC_PASS
rpcbind=127.0.0.1
rpcallowip=127.0.0.1
rpcport=24761
addnode=node1.fixedcoin.org
addnode=node2.fixedcoin.org
fallbackfee=0.0001
EOF
  echo "Wrote $CONF"
fi

echo "Starting fixedcoind..."
fixedcoind -datadir="$DATADIR" -conf="$CONF" &
PID_NODE=$!

for i in $(seq 1 90); do
  if fixedcoin-cli -datadir="$DATADIR" getblockchaininfo >/dev/null 2>&1; then
    echo "RPC ready"
    break
  fi
  sleep 2
done

fixedcoin-cli -datadir="$DATADIR" createwallet "mining" 2>/dev/null || true
fixedcoin-cli -datadir="$DATADIR" loadwallet "mining" 2>/dev/null || true

echo "Starting stratum..."
python3 /app/stratum/server.py &
PID_STRATUM=$!

echo "Starting monitor on :5050..."
python3 /app/monitor/app.py &
PID_MON=$!

trap 'kill $PID_NODE $PID_STRATUM $PID_MON 2>/dev/null' EXIT
wait
