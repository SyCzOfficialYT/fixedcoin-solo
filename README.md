# FixedCoin Solo Mining (Docker)

Solo stack for **FixedCoin (FIX)** – SHA-256, Bitcoin-style:

- `fixedcoind` full node (v29.1.3)
- Python **Stratum** (VarDiff + fixed `d=` password)
- **Flask dashboard** (shares, blocks, maturity countdown)

## Specs (network)

| | |
|--|--|
| Algorithm | SHA-256 |
| Block time | ~10 minutes |
| Coinbase maturity | **100 blocks** (~16.7 h) |
| Address | Bech32 `fix1...` |
| RPC | 24761 |
| P2P | 24768 |

## Quick start

```bash
git clone https://github.com/SyCzOfficialYT/fixedcoin-solo.git
cd fixedcoin-solo
cp config/config.example.yaml config/config.yaml
# Edit: rpc.password + pool.payout_address (fix1...)
sudo docker compose up -d --build
```

- Dashboard: http://HOST:5050  
- Stratum: `stratum+tcp://HOST:3333`  
- User: `fix1....worker1`  
- Password: `x` (VarDiff) or `d=50000` (fixed diff)

## Miner example (cgminer / ASIC)

```
-o stratum+tcp://YOUR_IP:3333 -u fix1q...youraddress.rig1 -p d=10000
```

## Notes

- First start syncs the chain (can take a while).
- Maturity is **100 blocks** (not FreeCash 14400).
- Coinbase is **single-output** to your payout address.
- Chain data lives in Docker volume `fix-data`.

## License

MIT – layout adapted from the FreeCash solo stack for FixedCoin.
