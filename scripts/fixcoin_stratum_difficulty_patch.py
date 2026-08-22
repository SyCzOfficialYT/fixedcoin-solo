#!/usr/bin/env python3
"""Patch the generated Stratum adapter to use FixedCoin's share-difficulty scale.

FixedCoin has two intentionally different difficulty scales:

* Stratum share difficulty uses the chain's powLimit. This is the scale used by
  the configured pool difficulty (13354 by default).
* Network/Explorer difficulty follows FixedCoin Core's Bitcoin-compatible
  difficulty-1 target and therefore remains separate from Stratum share work.

Keeping these conversions separate prevents accepted shares from being logged
with astronomically large work values while preserving the node's canonical
network difficulty.
"""
from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parent.parent
PATH = ROOT / "stratum" / "server_full.py"

FIXCOIN_POW_LIMIT = int(
    "00000fffffffffffffffffffffffffffffffffffffffffffffffffffffffffff", 16
)
DIFF1_TARGET = 0x00000000FFFF0000000000000000000000000000000000000000000000000000


def replace_function(source: str, name: str, replacement: str) -> str:
    tree = ast.parse(source)
    target = next(
        (
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == name
        ),
        None,
    )
    if target is None:
        raise RuntimeError(f"generated Stratum function {name!r} not found")
    lines = source.splitlines(keepends=True)
    start = sum(map(len, lines[: target.lineno - 1]))
    end = sum(map(len, lines[: target.end_lineno]))
    return source[:start] + replacement.rstrip() + "\n" + source[end:]


def patch() -> None:
    if not PATH.exists():
        raise RuntimeError(f"generated Stratum adapter missing: {PATH}")

    text = PATH.read_text()

    difficulty_to_target = f'''def difficulty_to_target(diff):
    """Convert FixedCoin Stratum share difficulty to a PoW target."""
    return int(FIXCOIN_POW_LIMIT / max(float(diff), 0.0001))
'''
    target_to_difficulty = '''def target_to_difficulty(target):
    """Convert a share hash/target integer to FixedCoin Stratum difficulty."""
    target = int(target)
    if target <= 0:
        return 0.0
    return FIXCOIN_POW_LIMIT / target
'''

    text = replace_function(text, "difficulty_to_target", difficulty_to_target)
    text = replace_function(text, "target_to_difficulty", target_to_difficulty)

    canonical = '''def canonical_difficulty(nbits):
    """Return FixedCoin Core's canonical network difficulty (Diff1 scale)."""
    return DIFF1_TARGET / bits_to_target(nbits)
'''
    if "def canonical_difficulty(" in text:
        text = replace_function(text, "canonical_difficulty", canonical)
    else:
        marker = "def difficulty_to_target(diff):"
        if marker not in text:
            raise RuntimeError("difficulty conversion marker missing")
        text = text.replace(marker, canonical + "\n" + marker, 1)

    # Network difficulty must remain Core/Explorer-compatible; only share work
    # uses FIXCOIN_POW_LIMIT.
    wrong = "net_diff = target_to_difficulty(bits_to_target(nbits))"
    correct = "net_diff = canonical_difficulty(nbits)"
    count = text.count(wrong)
    if count != 1:
        raise RuntimeError(
            f"network difficulty marker mismatch: expected 1, found {count}"
        )
    text = text.replace(wrong, correct, 1)

    # Make the constants explicit in generated source and fail loudly if a
    # future generator changes the structure unexpectedly.
    if "FIXCOIN_POW_LIMIT = " not in text:
        marker = "# ADAPT_VERSION="
        line_end = text.find("\n", text.find(marker))
        if line_end < 0:
            raise RuntimeError("adapter version marker missing")
        text = (
            text[:line_end]
            + f"\n\nFIXCOIN_POW_LIMIT = {FIXCOIN_POW_LIMIT}\n"
            + f"DIFF1_TARGET = {DIFF1_TARGET}\n"
            + text[line_end:]
        )
    else:
        # The consensus patch already injects the constant. Add DIFF1_TARGET
        # next to it if this generated revision does not have it yet.
        if "DIFF1_TARGET = " not in text:
            marker = f"FIXCOIN_POW_LIMIT = {FIXCOIN_POW_LIMIT}"
            if marker not in text:
                raise RuntimeError("unexpected FixedCoin powLimit value")
            text = text.replace(
                marker,
                marker + f"\nDIFF1_TARGET = {DIFF1_TARGET}",
                1,
            )

    ast.parse(text)
    PATH.write_text(text)


def verify() -> None:
    ns = {}
    source = PATH.read_text()
    exec(compile(source, str(PATH), "exec"), ns, ns)

    assert ns["FIXCOIN_POW_LIMIT"] == FIXCOIN_POW_LIMIT
    assert ns["DIFF1_TARGET"] == DIFF1_TARGET

    # FixedCoin Stratum scale: difficulty <-> target must round-trip exactly.
    for diff in (1, 1000, 13354, 50000):
        target = ns["difficulty_to_target"](diff)
        roundtrip = ns["target_to_difficulty"](target)
        if abs(roundtrip - diff) > 1e-9:
            raise RuntimeError(
                f"share difficulty regression failed: {diff} -> {target} -> {roundtrip}"
            )

    # The known Core/Explorer regression must remain unchanged.
    reference = ns["canonical_difficulty"]("19600c8f")
    if abs(reference - 44715709.803317755) > 0.01:
        raise RuntimeError(f"network difficulty regression failed: {reference}")

    text = source
    assert f"return int(FIXCOIN_POW_LIMIT / max(float(diff), 0.0001))" in text
    assert "return FIXCOIN_POW_LIMIT / target" in text
    assert "net_diff = canonical_difficulty(nbits)" in text
    assert "net_diff = target_to_difficulty(bits_to_target(nbits))" not in text


if __name__ == "__main__":
    patch()
    verify()
    print(
        "FixedCoin Stratum difficulty patch PASS: "
        "share scale=powLimit, network scale=Core/Diff1"
    )
