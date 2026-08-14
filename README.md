# FixedCoin Solo Mining (Docker)

Same stack as FreeCash solo: **fixedcoind + Stratum + full Live-Competition dashboard**.

## One-shot after clone / git pull

```bash
cd fixedcoin-solo
git pull --ff-only
chmod +x tools/install_ui.sh tools/deploy_ui.sh
./tools/install_ui.sh          # pulls real FCH solo UI, renames to FIX
sudo docker compose up -d --build
sudo ./tools/deploy_ui.sh      # patches stratum (no DEV_ADDRESS), copies UI into container
```

Dashboard: **http://HOST:5050**  
Stratum: **stratum+tcp://HOST:3333** · User `fix1….worker` · Pass `x` or `d=10000`

`config/config.yaml` and payout `fix1…` are auto-created on first boot.

## Logs (what is happening)

```bash
# Everything (node + stratum + dashboard)
sudo docker logs -f fixedcoin-solo

# Last 100 lines
sudo docker logs fixedcoin-solo --tail 100

# Only stratum / share / block lines
sudo docker logs fixedcoin-solo 2>&1 | grep -E "ACCEPT|BLOCK|ERROR|authorized|listening|Stratum|Payout|reject|DEV_ADDRESS|NameError"

# Live filter
sudo docker logs -f fixedcoin-solo 2>&1 | grep -E "ACCEPT|BLOCK|ERROR|WARN|authorized|listening"
```

## Specs

| | |
|--|--|
| Algo | SHA-256 |
| Block time | ~10 min |
| Maturity | 100 blocks |
| Address | `fix1…` |
| RPC / P2P | 24761 / 24768 |

## Notes

- `tools/deploy_ui.sh` patches server **only in a temp dir** then `docker cp` — working tree stays clean (like FCH 61fb618).
- `tools/rebuild_blocks_log.py` = wallet only, **no chain scan**.
