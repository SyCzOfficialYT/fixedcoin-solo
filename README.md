# FixedCoin Solo Mining (Docker)

Production-oriented FixedCoin solo stack: **fixedcoind + FixedCoin-adapted Stratum + Live dashboard**.

## Important: block-found semantics

A miner finding a hash below the network target is only a **block candidate**. The node is the final authority. The Stratum server therefore does **not** record or announce `BLOCK ACCEPTED` until `submitblock` succeeds **and** the exact candidate hash is visible through `getblock` at the expected height.

This is critical because JSON-RPC `submitblock` normally returns `null` on success. A generic RPC helper that also returns `null` on errors can otherwise turn a rejected block into a false `BLOCK ACCEPTED` event.

## One-shot after clone / git pull

```bash
cd fixedcoin-solo
git pull --ff-only
chmod +x tools/install_ui.sh tools/deploy_ui.sh
sudo docker compose up -d --build
```

Dashboard: **http://HOST:5050**  
Stratum: **stratum+tcp://HOST:3333** · User `fix1….worker` · Pass `x` or `d=13354`

The solo Stratum enforces the configured fixed share difficulty (`fixed_difficulty`, default **13354**) whenever the miner explicitly supplies a `d=` / `diff=` password. A stale miner password such as `d=13111` therefore cannot silently change the pool share target.

`config/config.yaml` and the persistent `fix1…` payout address are created/retained on first boot.

## Logs

```bash
sudo docker logs -f fixedcoin-solo
sudo docker logs fixedcoin-solo --tail 100
sudo docker logs fixedcoin-solo 2>&1 | grep -E "ACCEPT|BLOCK|ERROR|WARN|authorized|listening|Payout|submitblock"
```

For a genuine block you must see the sequence:

```text
*** BLOCK CANDIDATE ***
*** BLOCK ACCEPTED ***
```

A rejected or unverified candidate is logged as:

```text
submitblock rejected/unverified: ...
```

## Addresses in historical blocks

`getblock` shows the **coinbase outputs embedded in the blockchain**. Addresses such as legacy-looking `dB2...`, `iUv...`, `Tz...`, or other `fix1...` addresses in old network blocks are **not wallet addresses created by this container and cannot be deleted from the blockchain**. They are historical recipients of those blocks.

The pool payout address is separate and is taken from the persistent `payout_address` state / `FIX_PAYOUT_ADDRESS`. Do not rewrite or delete historical chain data merely to make those addresses disappear from a block explorer or chain scan.

## Specs

| | |
|--|--|
| Algo | SHA-256 |
| Block time | ~10 min |
| Maturity | 100 blocks |
| Address | `fix1…` |
| RPC / P2P | 24761 / 24768 |

## Notes

- `stratum/server.py` generates the adapted Stratum implementation during the image build/startup path.
- The current adapter is pinned to the known-good FixedCoin/FreeCash Stratum base commit and carries the FixedCoin-specific coinbase, GBT, fixed-difficulty, and verified-submit patches.
- `tools/rebuild_blocks_log.py` is wallet-only; it does not rewrite or delete chain history.
