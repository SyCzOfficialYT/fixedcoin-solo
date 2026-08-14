#!/bin/sh
# Install EXACT FCH full solo dashboard (1:1 structure, FIX branding)
set -e
cd "$(dirname "$0")/.."
python3 tools/patch_dashboard.py
# Full monitor app from FCH mainline, maturity 100 for FIX
curl -fsSL "https://raw.githubusercontent.com/SyCzOfficialYT/freecash-coin/61fb618fdda4/monitor/app.py" \
  | sed 's/FreeCash/FixedCoin/g;s/FCH/FIX/g;s/freecash/fixedcoin/g;s/COINBASE_MATURITY = 14400/COINBASE_MATURITY = 100/g;s/\[:14400\]/[:1000]/g' \
  > monitor/app.py
echo "==> Sanity"
grep -E "heightStrip|Live Competition|FIX Solo" monitor/templates/dashboard.html | head -5
grep -E "COINBASE_MATURITY|/api/logs" monitor/app.py | head -5
echo "OK – same dashboard as FCH container (FIX-branded)."
