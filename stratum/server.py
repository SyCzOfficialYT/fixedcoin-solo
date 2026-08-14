#!/usr/bin/env python3
"""FixedCoin Stratum – base from FreeCash a88d, adapted for FIX single coinbase."""
import re, urllib.request, runpy, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FULL = HERE / "server_full.py"
URL = "https://raw.githubusercontent.com/SyCzOfficialYT/freecash-coin/a88d89675b/stratum/server.py"

SINGLE_COINBASE = '''def build_coinbase_parts(height, miner_value_sats, miner_spk, en1_size=4, en2_size=4, *args, **kwargs):
    """Single-output coinbase (FixedCoin / Bitcoin-style). Ignores extra args (legacy dev_spk)."""
    tag = b"/FIX-Solo/"
    height_script = bip34_height(height)
    scriptsig_len = len(height_script) + en1_size + en2_size + len(tag)
    part1 = struct.pack("<I", 2) + b"\\x01" + b"\\x00" * 32 + struct.pack("<I", 0xFFFFFFFF)
    part1 += encode_varint(scriptsig_len) + height_script
    part2 = tag + struct.pack("<I", 0xFFFFFFFF) + b"\\x01"
    part2 += struct.pack("<Q", int(miner_value_sats))
    part2 += encode_varint(len(miner_spk)) + miner_spk
    part2 += struct.pack("<I", 0)
    return binascii.hexlify(part1).decode(), binascii.hexlify(part2).decode()
'''

def adapt(text: str) -> str:
    text = text.replace(
        "FreeCash Solo Stratum",
        "FixedCoin Solo Stratum",
    )
    text = text.replace('job_interval", 20)', 'job_interval", 30)')
    text = text.replace("+ 14400", "+ 100")
    text = text.replace("blog[-20:]", "blog[-1000:]")
    text = text.replace(" FCH", " FIX")
    text = text.replace("FreeCash", "FixedCoin")
    text = text.replace("/FCH-Solo/", "/FIX-Solo/")

    # Drop DEV_ADDRESS constant
    text = re.sub(r"^DEV_ADDRESS\s*=\s*.*$\n", "", text, flags=re.M)

    # Drop lines that reference DEV_ADDRESS
    text = "\n".join(l for l in text.splitlines() if "DEV_ADDRESS" not in l) + "\n"

    # Drop dev_spk assignment / emits if any remain
    text = re.sub(r"^\s*self\.dev_spk\s*=.*$\n", "", text, flags=re.M)
    text = re.sub(r"^\s*emit\(\"INFO\", f\"dev/governance.*$\n", "", text, flags=re.M)

    # Replace build_coinbase_parts entirely (match until next def)
    text = re.sub(
        r"def build_coinbase_parts\(.*?\n(?=def )",
        SINGLE_COINBASE + "\n",
        text,
        count=1,
        flags=re.S,
    )

    # Calls still pass self.dev_spk as 4th arg – make them work via *args in new fn.
    # Optional: strip , self.dev_spk if still present
    text = text.replace(", self.dev_spk", "")

    # Startup log without DEV
    text = re.sub(
        r'emit\("INFO", f"Dev/governance.*?\)\n',
        'emit("INFO", "Coinbase: single output → PAYOUT_ADDRESS")\n',
        text,
    )
    return text

# Always rebuild so patches apply
if FULL.exists():
    FULL.unlink()

print("Fetching stratum base…")
raw = urllib.request.urlopen(URL, timeout=60).read().decode()
adapted = adapt(raw)

# Sanity checks
assert "def build_coinbase_parts" in adapted
assert "DEV_ADDRESS" not in adapted, "DEV_ADDRESS still present"
assert "/FIX-Solo/" in adapted or "FIX-Solo" in adapted

FULL.write_text(adapted)
print("Wrote", FULL, FULL.stat().st_size)

sys.argv[0] = str(FULL)
runpy.run_path(str(FULL), run_name="__main__")
