FROM python:3.12-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates wget tar \
    && rm -rf /var/lib/apt/lists/*

ARG FIX_VER=29.1.3
# Exact full FreeCash dashboard revision with live shares, live competition,
# block history/maturity and CLI terminal.
ARG FCH_DASHBOARD_COMMIT=a3016f07fc36f9e25d86c4f825f9185859bae17b
RUN mkdir -p /opt/fixedcoin \
 && curl -fsSL -o /tmp/fix.tgz \
    "https://github.com/Fixed-Blockchain/fixedcoin/releases/download/v${FIX_VER}/fixedcoin-${FIX_VER}-x86_64-linux-gnu.tar.gz" \
 && tar -xzf /tmp/fix.tgz -C /opt/fixedcoin --strip-components=1 \
 && rm /tmp/fix.tgz \
 && ln -sf /opt/fixedcoin/bin/fixedcoind /usr/local/bin/fixedcoind \
 && ln -sf /opt/fixedcoin/bin/fixedcoin-cli /usr/local/bin/fixedcoin-cli

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . /app

# Install the exact FreeCash UI revision into the FixedCoin image.
# Only presentation labels are adapted: FCH -> FIX.
RUN curl -fsSL \
    "https://raw.githubusercontent.com/SyCzOfficialYT/freecash-coin/${FCH_DASHBOARD_COMMIT}/monitor/templates/dashboard.html" \
    -o /app/monitor/templates/dashboard.html \
 && python3 - <<'PY'
from pathlib import Path
p=Path('/app/monitor/templates/dashboard.html')
s=p.read_text()
s=s.replace('FCH Solo','FIX Solo').replace('FCH','FIX')
s=s.replace('14400','{{ maturity_blocks }}')
assert 'Live Shares' in s
assert 'Blocks · Coinbase maturity countdown' in s
assert 'CLI Terminal' in s
assert 'Live Competition' in s
assert 'FCH' not in s
p.write_text(s)
print('Exact FreeCash dashboard installed:', len(s), 'bytes')
PY

# Make the FixedCoin backend expose every field required by that exact UI and
# make freshly-found coinbases visible as immature before wallet indexing catches up.
RUN python3 /app/tools/patch_fixedcoin_dashboard.py

RUN STRATUM_BUILD_ONLY=1 python3 /app/stratum/server.py \
 && python3 - <<'PY'
from pathlib import Path
p=Path('/app/stratum/server_full.py'); s=p.read_text()
for old in (
    'rpc("getblocktemplate", [{"rules": []}])',
    'rpc("getblocktemplate", [])',
):
    s=s.replace(old, 'rpc("getblocktemplate", [{"rules": ["segwit"]}])')
for line in s.splitlines():
    if 'getblocktemplate' in line and 'rules": ["segwit"]' not in line:
        raise SystemExit(f'unsafe GBT call remains: {line}')
old='''def rpc(method, params=None):
    try:
        r = requests.post(
            f"http://{RPC_HOST}:{RPC_PORT}",
            json={"jsonrpc": "1.0", "id": "s", "method": method, "params": params or []},
            auth=HTTPBasicAuth(RPC_USER, RPC_PASS), timeout=60,
        )
        r.raise_for_status()
        data = r.json()
        if data.get("error"):
            log.error("RPC %s: %s", method, data["error"])
            return None
        return data.get("result")
    except Exception as e:
        log.error("RPC %s: %s", method, e)
        return None
'''
new='''def rpc(method, params=None):
    try:
        r = requests.post(
            f"http://{RPC_HOST}:{RPC_PORT}",
            json={"jsonrpc": "1.0", "id": "s", "method": method, "params": params or []},
            auth=HTTPBasicAuth(RPC_USER, RPC_PASS), timeout=60,
        )
        data = r.json()
        if data.get("error"):
            err = data["error"]
            code = err.get("code") if isinstance(err, dict) else None
            if method == "getblocktemplate" and code == -10:
                log.warning("RPC getblocktemplate: node still syncing (-10); waiting for chain tip")
            else:
                log.error("RPC %s: %s", method, err)
            return None
        if not r.ok:
            log.error("RPC %s: HTTP %s", method, r.status_code)
            return None
        return data.get("result")
    except Exception as e:
        log.error("RPC %s: %s", method, e)
        return None
'''
if old not in s:
    raise SystemExit('RPC helper shape changed; refusing to apply unsafe patch')
p.write_text(s.replace(old,new,1))
print('GBT/RPC verification: OK')
PY
RUN python3 -m py_compile /app/monitor/app.py /app/stratum/server.py /app/stratum/server_full.py
RUN chmod +x /app/docker/entrypoint.sh

ENV FIX_DATADIR=/data/fixedcoin
EXPOSE 3333 5050 24768
ENTRYPOINT ["/app/docker/entrypoint.sh"]
