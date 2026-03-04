# Quick Start

This tutorial runs a minimal end-to-end backtest.

## 1) Prepare sample CSV

Create `sample.csv`:

```csv
Date,Open,High,Low,Close,Volume,OpenInterest
2024-01-02,100,102,99,101,10000,0
2024-01-03,101,103,100,102,11000,0
2024-01-04,102,104,101,103,12000,0
2024-01-05,103,105,102,104,13000,0
```

## 2) Create a strategy

```python
from bucktrader.cortex import Cortex
from bucktrader.feed import GenericCSVData
from bucktrader.strategy import Strategy


class BuyAndHold(Strategy):
    def __init__(self):
        super().__init__()
        self._done = False

    def _next(self):
        if not self._done:
            self.buy(size=1)
            self._done = True


data = GenericCSVData(
    dataname="sample.csv",
    dtformat="%Y-%m-%d",
    open_col=1,
    high_col=2,
    low_col=3,
    close_col=4,
    volume_col=5,
    openinterest_col=6,
)

cortex = Cortex(preload=False, runonce=False)
cortex.adddata(data)
cortex.addstrategy(BuyAndHold)
results = cortex.run()

print("Final value:", cortex.broker.getvalue())
print("Orders:", len(results[0]._orders))
```

## 3) Add analyzer and observer

```python
from bucktrader.analyzers import Returns
from bucktrader.observers import DrawDown

cortex.addanalyzer(Returns)
cortex.addobserver(DrawDown)
results = cortex.run()
```

## 4) Plot the run

```python
cortex.plot(iplot=True)
```
