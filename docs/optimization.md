# Optimization Guide

Bucktrader supports parameter optimization by running strategy variants across parameter grids.

## Basic Optimization

```python
from bucktrader.cortex import Cortex
from bucktrader.strategy import Strategy


class SmaCross(Strategy):
    params = (("fast", 10), ("slow", 30))
    # strategy logic omitted


cortex = Cortex(maxcpus=0)  # use all available CPUs
cortex.optstrategy(SmaCross, fast=[5, 10, 15], slow=[20, 30, 40])
opt_runs = cortex.run()
```

`opt_runs` is a list of lists, where each inner list contains one executed strategy instance.

## Capturing Optimization Output

Use analyzers to collect comparable metrics:

```python
from bucktrader.analyzers import Returns, SharpeRatio, DrawDown

cortex.addanalyzer(Returns)
cortex.addanalyzer(SharpeRatio)
cortex.addanalyzer(DrawDown)
```

Then flatten and rank:

```python
rows = []
for run in opt_runs:
    strat = run[0]
    rows.append(
        {
            "fast": strat.p.fast,
            "slow": strat.p.slow,
            "rtot": strat.analyzers.returns.rets.rtot,
        }
    )
rows = sorted(rows, key=lambda x: x["rtot"], reverse=True)
```

## Notes

- Keep strategy logic deterministic when comparing parameter sets.
- Use the same feed window for all variants.
- Prefer a small first grid, then refine around top candidates.
