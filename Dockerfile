FROM python:3.12-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates wget tar \
    && rm -rf /var/lib/apt/lists/*

ARG FIX_VER=29.1.3
# Exact NEW-FCH dashboard revision from freecash-coin.
ARG FCH_DASHBOARD_COMMIT=b73f888c7a154015056cdce765fe79dda1a20215
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

# IMPORTANT: the current FreeCash dashboard lives under monitor/templates,
# not dashboard/templates. Pin the exact NEW-FCH branch head so the image
# cannot silently fall back to an older UI.
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
assert 'Gefundene Blöcke' in s
assert 'CLI Terminal' in s
assert 'Live Competition' in s
assert 'FCH' not in s
p.write_text(s)
print('Exact FreeCash NEW-FCH dashboard installed:', len(s), 'bytes')
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
p.write_text(s)
print('GBT verification: all getblocktemplate calls use segwit rules')
PY

# Generated Stratum must use FixedCoin powLimit for share difficulty while
# retaining Core's Bitcoin-compatible Diff1 scale for network difficulty.
RUN python3 /app/scripts/fixcoin_stratum_difficulty_patch.py

RUN python3 -m py_compile /app/monitor/app.py /app/stratum/server.py /app/stratum/server_full.py /app/scripts/fixcoin_stratum_difficulty_patch.py
RUN chmod +x /app/docker/entrypoint.sh

ENV FIX_DATADIR=/data/fixedcoin
EXPOSE 3333 5050 24768
ENTRYPOINT ["/app/docker/entrypoint.sh"]
