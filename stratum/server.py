#!/usr/bin/env python3
"""FixedCoin Stratum – downloads known-good base and adapts for FIX (single coinbase, maturity 100)."""
import re, urllib.request, runpy, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FULL = HERE / "server_full.py"
URL = "https://raw.githubusercontent.com/SyCzOfficialYT/freecash-coin/a88d89675b/stratum/server.py"

def adapt(text: str) -> str:
    text = text.replace(
        "FreeCash Solo Stratum – soft VarDiff + grace window + 2-out coinbase (miner+dev)",
        "FixedCoin Solo Stratum – soft VarDiff + single-output coinbase",
    )
    text = text.replace('job_interval", 20)', 'job_interval", 30)')
    text = text.replace('job["height"] + 14400', 'job["height"] + 100')
    text = text.replace("job['height'] + 14400", "job['height'] + 100")
    text = text.replace("+ 14400", "+ 100")
    text = re.sub(r"^DEV_ADDRESS = .*\n", "", text, flags=re.M)
    text = text.replace(
        "INITIAL_REWARD_SATS = 25 * 100_000_000\nSUBSIDY_HALVING_INTERVAL = 576_000\nLAST_HALVING = 21\n",
        "INITIAL_REWARD_SATS = 1 * 100_000_000\nSUBSIDY_HALVING_INTERVAL = 4200\nLAST_HALVING = 14\n",
    )
    # remove dual-output setup
    text = text.replace(
        """            self.script_pubkey = address_to_scriptpubkey(PAYOUT_ADDRESS)\n            emit("INFO", f"scriptPubKey ready for {PAYOUT_ADDRESS}")\n            self.dev_spk = address_to_scriptpubkey(DEV_ADDRESS)\n            emit("INFO", f"dev/governance scriptPubKey ready for {DEV_ADDRESS}")\n""",
        """            self.script_pubkey = address_to_scriptpubkey(PAYOUT_ADDRESS)\n            emit("INFO", f"scriptPubKey ready for {PAYOUT_ADDRESS}")\n""",
    )
    text = text.replace(", self.dev_spk", "")
    text = text.replace("blog[-20:]", "blog[-1000:]")
    text = text.replace(" FCH", " FIX")
    text = text.replace("FreeCash", "FixedCoin")
    text = text.replace("/FCH-Solo/", "/FIX-Solo/")
    # critical: remove any remaining DEV_ADDRESS references
    text = re.sub(
        r'^\s*emit\("INFO", f"Dev/governance output.*\n',
        '    emit("INFO", "Coinbase: single output to PAYOUT_ADDRESS")\n',
        text,
        flags=re.M,
    )
    text = re.sub(r".*DEV_ADDRESS.*\n", "", text)
    # neutralize get_dev_reward usage if still present in builds
    text = text.replace("dev_sats = get_dev_reward_sats(height)", "dev_sats = 0")
    return text

# Always re-adapt from upstream so fixes apply (delete stale server_full)
if FULL.exists():
    FULL.unlink()

print("Fetching stratum base…")
raw = urllib.request.urlopen(URL, timeout=60).read().decode()
adapted = adapt(raw)
if "DEV_ADDRESS" in adapted:
    # last-resort strip
    adapted = "\n".join(l for l in adapted.splitlines() if "DEV_ADDRESS" not in l) + "\n"
FULL.write_text(adapted)
print("Wrote", FULL, FULL.stat().st_size, "DEV_ADDRESS left:", "DEV_ADDRESS" in adapted)

sys.argv[0] = str(FULL)
runpy.run_path(str(FULL), run_name="__main__")
