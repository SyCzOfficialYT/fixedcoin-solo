#!/usr/bin/env python3
"""Verify FixedCoin RPC availability and basic chain integrity.

Checks:
- JSON-RPC authentication works
- getblockchaininfo is coherent
- genesis block is readable
- current tip is readable
- recent prev-hash links are continuous
- getnetworkinfo/getmininginfo/getblocktemplate are callable

This intentionally does not require the chain to advance while the test runs;
a node may legitimately have no new blocks during a short verification window.
"""
import os
import sys
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
import base64
import json

HOST = os.getenv("FIX_RPC_HOST", "127.0.0.1")
PORT = int(os.getenv("FIX_RPC_PORT", "24761"))
USER = os.getenv("FIX_RPCUSER", "fixrpc")
PASSWORD = os.getenv("FIX_RPCPASS", "FixedcoinSoloAutoRpc_ChangeMeIfPublic")
URL = f"http://{HOST}:{PORT}"


def rpc(method, params=None):
    payload = json.dumps({"jsonrpc": "1.0", "id": "verify", "method": method, "params": params or []}).encode()
    req = Request(URL, data=payload, headers={"Content-Type": "application/json"})
    token = base64.b64encode(f"{USER}:{PASSWORD}".encode()).decode()
    req.add_header("Authorization", f"Basic {token}")
    try:
        with urlopen(req, timeout=10) as r:
            data = json.load(r)
    except (HTTPError, URLError, OSError) as e:
        raise RuntimeError(f"RPC transport failed: {e}") from e
    if data.get("error"):
        raise RuntimeError(f"RPC {method} failed: {data['error']}")
    return data.get("result")


def main():
    print(f"[verify] RPC endpoint: {URL}")
    info = rpc("getblockchaininfo")
    height = int(info.get("blocks", -1))
    headers = int(info.get("headers", -1))
    chain = info.get("chain")
    if height < 0 or headers < height:
        raise RuntimeError(f"invalid blockchaininfo blocks={height} headers={headers}")
    print(f"[verify] RPC OK: chain={chain} height={height} headers={headers}")

    genesis_hash = rpc("getblockhash", [0])
    genesis = rpc("getblock", [genesis_hash, 1])
    if genesis.get("height") != 0 or genesis.get("hash") != genesis_hash:
        raise RuntimeError("genesis block is inconsistent")
    print(f"[verify] genesis OK: {genesis_hash}")

    tip_hash = rpc("getblockhash", [height])
    tip = rpc("getblock", [tip_hash, 1])
    if tip.get("height") != height or tip.get("hash") != tip_hash:
        raise RuntimeError("tip block is inconsistent")
    print(f"[verify] tip OK: #{height} {tip_hash}")

    # Verify the most recent chain links. This catches a node whose RPC responds
    # but whose block index/prev-hash chain is malformed.
    checks = min(25, height)
    child = tip
    for h in range(height - 1, max(-1, height - checks - 1), -1):
        parent_hash = rpc("getblockhash", [h])
        parent = rpc("getblock", [parent_hash, 1])
        if child.get("previousblockhash") != parent_hash:
            raise RuntimeError(f"broken chain link at child #{child.get('height')} -> #{h}")
        child = parent
    print(f"[verify] recent chain links OK: {checks} blocks")

    network = rpc("getnetworkinfo")
    mining = rpc("getmininginfo")
    print(f"[verify] network RPC OK: connections={network.get('connections', '?')}")
    print(f"[verify] mining RPC OK: blocks={mining.get('blocks', '?')}")

    try:
        template = rpc("getblocktemplate", [{}])
    except RuntimeError:
        # Some Bitcoin-derived nodes expect no params or a different template
        # rule set. Retry the plain call before declaring the RPC path broken.
        template = rpc("getblocktemplate")
    if not isinstance(template, dict) or not template.get("height"):
        raise RuntimeError("getblocktemplate returned no usable template")
    print(f"[verify] getblocktemplate OK: height={template.get('height')} bits={template.get('bits')}")

    print("[verify] PASS: RPC works and the chain index/links are coherent.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        print(f"[verify] FAIL: {e}", file=sys.stderr)
        raise SystemExit(1)
