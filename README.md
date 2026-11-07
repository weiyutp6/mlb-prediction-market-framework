# MLB Prediction-Market Framework

A paper-trading framework that compares model fair probabilities for live MLB games with order-book prices on Polymarket, sizes positions with fractional Kelly, and logs or places orders.

The fair-probability tables in this public version come from a deliberately simple Poisson run-scoring model. They are **not calibrated to data and carry no trading edge**. They are there so the whole pipeline runs end to end, and so a calibrated table can be dropped into `heatmaps.py` behind the same lookup API.

## Pipeline

```
Polymarket Gamma + CLOB
        |
  preprocessing.py    classify markets (moneyline / run line / totals), attach order books
        |
  signals.py          parse score + inning, compare fair probability with CLOB mid
        |
  sizing.py           fractional Kelly stake with a hard cap
        |
  executor.py         paper log, or GTC limit order
        |
  bot.py              polling loop
```

| File | Role |
|---|---|
| `market_data.py` | Gamma event discovery and CLOB quotes (bid, ask, mid, spread, depth). |
| `preprocessing.py` | Market classification with keyword fallbacks, dataclasses, batched order-book enrichment. |
| `signals.py` | Game-state parser, edge and depth filters for ML, run line (-1.5) and totals. |
| `heatmaps.py` | Fair-probability lookups. Demo model: independent Poisson scoring per half-inning. |
| `sizing.py` | Fractional Kelly: `stake = bankroll * fraction * edge / (1 - price)`, capped per bet. |
| `executor.py` | Paper mode logs; live mode posts a GTC limit order with an expiry. |
| `config.py` | Thresholds, bankroll, Kelly fraction. Wallet keys come from environment variables only. |

## Totals pricing

For an over/under line `L` and current total `t`, the threshold is `int(L - t)` (lines end in .5). The lookup returns `P(runs remaining <= threshold)`, which is `P(under)`; `P(over)` is its complement.

## Demo model assumptions

- Each team scores Poisson(0.5) runs per half-inning, independently.
- The full current half-inning is still to be played; the bottom of the 9th is always played.
- A tie after nine innings counts as half a win for each side.

These are simplifications. Real in-game win probability depends on base-out state, pitchers, park and more.

## Setup

```bash
pip install -r requirements.txt
python -m pytest          # offline tests, no network needed
python bot.py             # paper trading loop (PAPER_TRADING = True by default)
```

Live trading needs `POLYMARKET_PRIVATE_KEY` and `POLYMARKET_WALLET_ADDRESS` in your environment and `PAPER_TRADING = False` in `config.py`. Review the code and the risks first. Never commit keys.

## Disclaimer

For research and education only. Prediction-market trading can lose money, and rules differ by jurisdiction. Nothing here is investment advice.
