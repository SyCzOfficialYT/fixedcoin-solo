# FixedCoin Solo Mining (Docker)

Solo-Stack für **FixedCoin (FIX)** – analog FreeCash-Solo:

- `fixedcoind` (v29.1.3)
- Python-Stratum (VarDiff / `d=`)
- Flask-Dashboard
- **`config/config.yaml` wird beim Start automatisch geschrieben**
- **Payout-Adresse (`fix1…`) wird automatisch aus der Wallet erzeugt**

## Start (kein manuelles Config-Edit nötig)

```bash
git clone https://github.com/SyCzOfficialYT/fixedcoin-solo.git
cd fixedcoin-solo
sudo docker compose up -d --build
```

Logs:

```bash
sudo docker logs -f fixedcoin-solo
```

Du siehst u.a.:

```
[allinone] config.yaml ready
[allinone] Holding    fix1q…
[allinone] Dashboard  http://0.0.0.0:5050
```

- **Dashboard:** http://HOST:5050  
- **Stratum:** `stratum+tcp://HOST:3333`  
- **User:** `fix1….worker1` (oder die Holding-Adresse aus dem Log)  
- **Pass:** `x` oder `d=10000`

## Optional: RPC-Passwort härten

In `docker-compose.yml` Env setzen:

```yaml
environment:
  - FIX_RPCPASS=dein_sicheres_passwort
```

## Specs

| | |
|--|--|
| Algorithmus | SHA-256 |
| Blockzeit | ~10 min |
| Maturity | **100** Blöcke |
| Adresse | Bech32 `fix1…` |
| RPC / P2P | 24761 / 24768 |

## Hinweis

Erster Start = Chain-Sync. Volume `fix-data` hält Node + Stats persistent.
