#!/bin/sh
# Pull the real FreeCash solo dashboard (Live Competition, terminal, shares)
# and adapt it for FixedCoin. Run before deploy_ui.sh.
set -e
cd "$(dirname "$0")/.."
mkdir -p monitor/templates tools

echo "==> Full FCH solo dashboard -> FIX"
curl -fsSL "https://raw.githubusercontent.com/SyCzOfficialYT/freecash-coin/61fb618fdda4/monitor/templates/dashboard.html" \
  | sed 's/FreeCash/FixedCoin/g;s/FCH/FIX/g;s/freecash/fixedcoin/g;s/14400/100/g' \
  > monitor/templates/dashboard.html

curl -fsSL "https://raw.githubusercontent.com/SyCzOfficialYT/freecash-coin/61fb618fdda4/monitor/app.py" \
  | sed 's/FreeCash/FixedCoin/g;s/FCH/FIX/g;s/freecash/fixedcoin/g;s/COINBASE_MATURITY = 14400/COINBASE_MATURITY = 100/g;s/\[:14400\]/[:1000]/g' \
  > monitor/app.py

curl -fsSL "https://raw.githubusercontent.com/SyCzOfficialYT/freecash-coin/61fb618fdda4/tools/rebuild_blocks_log.py" \
  | sed 's/FreeCash/FixedCoin/g;s/FCH/FIX/g;s/freecash/fixedcoin/g;s/if payout and len(found)/if False and payout and len(found)/;s/\[-14400:\]/[-1000:]/g' \
  > tools/rebuild_blocks_log.py

echo "==> Sanity"
grep -E "Live Competition|/api/logs" monitor/templates/dashboard.html | head -3
grep -E "COINBASE_MATURITY|/api/logs" monitor/app.py | head -5
echo "OK. Next: chmod +x tools/deploy_ui.sh && sudo ./tools/deploy_ui.sh"
