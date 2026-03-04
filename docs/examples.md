# Example Strategies

These examples are intentionally small and easy to adapt.

## Buy And Hold

```python
from bucktrader.strategy import Strategy


class BuyAndHold(Strategy):
    def __init__(self):
        super().__init__()
        self._entered = False

    def _next(self):
        if not self._entered:
            self.buy(size=1)
            self._entered = True
```

## SMA Crossover

```python
from bucktrader.strategy import Strategy
from bucktrader.indicators import SMA


class SmaCross(Strategy):
    params = (("fast", 10), ("slow", 30), ("size", 1))

    def __init__(self):
        super().__init__()
        self.fast = SMA(self.data.close, period=self.p.fast)
        self.slow = SMA(self.data.close, period=self.p.slow)

    def _next(self):
        if len(self) < self.p.slow:
            return
        if self.position.size == 0 and self.fast[0] > self.slow[0]:
            self.buy(size=self.p.size)
        elif self.position.size > 0 and self.fast[0] < self.slow[0]:
            self.close()
```

## Bracket Example

```python
from bucktrader.strategy import Strategy


class BracketDemo(Strategy):
    def _next(self):
        if self.position.size == 0:
            entry = self.buy(size=1)
            self.sell(size=1, parent=entry, exectype="Limit", price=self.data.close[0] * 1.03)
            self.sell(size=1, parent=entry, exectype="Stop", price=self.data.close[0] * 0.97)
```

## Signal Strategy

```python
from bucktrader.signal import SignalStrategy
from bucktrader.indicators import RSI


class RsiSignal(SignalStrategy):
    params = (("period", 14),)

    def __init__(self):
        super().__init__()
        self.rsi = RSI(self.data.close, period=self.p.period)

    def signal_add(self):
        return 1 if self.rsi[0] < 30 else 0

    def signal_sub(self):
        return 1 if self.rsi[0] > 70 else 0
```
