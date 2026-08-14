#!/usr/bin/env python3
"""Verify FixedCoin RPC availability and basic chain integrity.

Run normally from the host with::

    python3 tools/verify_chain_rpc.py

If the FixedCoin node is running in the project's Docker container and the
host cannot reach its private RPC listener, the verifier automatically runs
itself inside ``fixedcoin-solo``. Set ``FIX_RPC_NO_DOCKER=1`` to disable that
fallback and force a direct RPC connection.

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

import base64
import json
import os
import shutil
import subprocess
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

HOST = os.getenv("FIX_RPC_HOST", "127.0.0.1")
PORT = int(os.getenv("FIX_RPC_PORT", "24761"))
USER = os.getenv("FIX_RPCUSER", "fixrpc")
PASSWORD = os.getenv("FIX_RPCPASS", "FixedcoinSoloAutoRpc_ChangeMeIfPublic")
CONTAINER = os.getenv("FIX_RPC_CONTAINER", "fixedcoin-solo")
URL = f"http://{HOST}:{PORT}"


def rpc(method, params=None):
    payload = json.dumps(
        {"jsonrpc": "1.0", "id": "verify", "method": method, "params": params or []}
    ).encode()
    req = Request(URL, data=payload, headers={"Content-Type": "application/json"})
    token = base64.b64encode(f"{USER}:{PASSWORD}".encode()).decode()
    req.add_header("Authorization", f"Basic {token}")
    try:
        with urlopen(req, timeout=10) as response:
            data = json.load(response)
    except (HTTPError, URLError, OSError) as exc:
        raise RuntimeError(f"RPC transport failed: {exc}") from exc
    if data.get("error"):
        raise RuntimeError(f"RPC {method} failed: {data['error']}")
    return data.get("result")


def _docker_fallback():
    """Run the verifier inside the all-in-one container when host RPC is private."""
    if os.getenv("FIX_RPC_NO_DOCKER") == "1":
        return False
    if os.getenv("FIX_RPC_IN_CONTAINER") == "1":
        return False
    docker = shutil.which("docker")
    if not docker:
        return False

    try:
        state = subprocess.run(
            [docker, "inspect", "-f", "{{.State.Running}}", CONTAINER],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return False

    if state.returncode != 0 or state.stdout.strip().lower() != "true":
        return False

    print(f"[verify] host RPC {URL} is unreachable; retrying inside Docker container {CONTAINER}")
    env = {
        "FIX_RPC_HOST": "127.0.0.1",
        "FIX_RPC_PORT": str(PORT),
        "FIX_RPCUSER": USER,
        "FIX_RPCPASS": PASSWORD,
        "FIX_RPC_IN_CONTAINER": "1",
    }
    cmd = [docker, "exec"]
    for key, value in env.items():
        cmd.extend(["-e", f"{key}={value}"])
    cmd.extend([CONTAINER, "python3", "/app/tools/verify_chain_rpc.py"])

    result = subprocess.run(cmd, check=False)
    return result.returncode == 0


def main():
    print(f"[verify] RPC endpoint: {URL}")
    try:
        return verify_rpc()
    except RuntimeError as exc:
        # The compose setup intentionally keeps RPC private to the all-in-one
        # container. A host-side invocation therefore cannot reach 127.0.0.1:
        # 24761. Automatically run the exact same verifier inside the container.
        if _docker_fallback():
            return 0
        raise exc


def verify_rpc():
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
        template = rpc("getblocktemplate")
    if not isinstance(template, dict) or not template.get("height"):
        raise RuntimeError("getblocktemplate returned no usable template")
    print(f"[verify] getblocktemplate OK: height={template.get('height')} bits={template.get('bits')}")

    print("[verify] PASS: RPC works and the chain index/links are coherent.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[verify] FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
