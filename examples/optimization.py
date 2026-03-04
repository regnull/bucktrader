"""Parameter optimization example.

Optimizes fast and slow SMA periods for a crossover strategy on AAPL.
Demonstrates: optstrategy, parameter grid search, sorting OptReturn results.
"""

from pathlib import Path
from typing import Any

from bucktrader.analyzers import Returns, TradeAnalyzer
from bucktrader.cortex import Cortex
from bucktrader.feed import GenericCSVData
from bucktrader.indicators import SMA

DATA_DIR = Path(__file__).parent / "data"

# Parameter grid to search.
FAST_PERIODS = [5, 10, 15, 20]
SLOW_PERIODS = [30, 40, 50, 60]
TOP_N = 5


class OptSmaCross:
    """SMA crossover strategy compatible with Cortex optimization.

    Accepts fast/slow periods as constructor kwargs so Cortex can
    inject different combinations during optimization.
    """

    def __init__(self, **kwargs: Any) -> None:
        self._params = kwargs
        self.datas: list[Any] = []
        self.data: Any = None
        self.broker: Any = None
        self.env: Any = None
        self.cortex: Any = None
        self._orders: list[Any] = []
        self._trades: dict[Any, list[Any]] = {}
        self._lineiterators = {0: [], 1: [], 2: []}
        self._analyzers: list[Any] = []
        self.stats: list[Any] = []
        self.analyzers: list[Any] = []
        self._fast_sma: Any = None
        self._slow_sma: Any = None
        self._bar = 0

    def start(self) -> None:
        fast = self._params.get("fast", 10)
        slow = self._params.get("slow", 30)
        self._fast_sma = SMA(self.data.close, period=fast)
        self._slow_sma = SMA(self.data.close, period=slow)

    def stop(self) -> None:
        pass

    def _next(self) -> None:
        self._bar += 1
        fast = self._params.get("fast", 10)
        slow = self._params.get("slow", 30)

        self._fast_sma.lines.forward()
        self._fast_sma.next()
        self._slow_sma.lines.forward()
        self._slow_sma.next()

        if self._bar < slow:
            return

        fast_val = self._fast_sma.lines.av[0]
        slow_val = self._slow_sma.lines.av[0]

        pos = self.broker.getposition(self.data)

        if pos.size == 0 and fast_val > slow_val:
            order = self.broker.buy(
                owner=self, data=self.data, size=10, exectype=0,
            )
            self._orders.append(order)
        elif pos.size > 0 and fast_val < slow_val:
            order = self.broker.sell(
                owner=self, data=self.data, size=pos.size, exectype=0,
            )
            self._orders.append(order)

    def notify_order(self, order: Any) -> None:
        pass

    def notify_trade(self, trade: Any) -> None:
        pass

    def notify_cashvalue(self, cash: float, value: float) -> None:
        pass

    def notify_fund(self, cash: float, value: float, fv: float, shares: float) -> None:
        pass


def main():
    cortex = Cortex(
        preload=False,
        runonce=False,
        stdstats=False,
        optreturn=True,
    )

    data = GenericCSVData(
        dataname=DATA_DIR / "aapl.csv",
        dtformat="%Y-%m-%d",
        open_col=1,
        high_col=2,
        low_col=3,
        close_col=4,
        volume_col=5,
        openinterest_col=6,
    )
    cortex.adddata(data)

    cortex.optstrategy(OptSmaCross, fast=FAST_PERIODS, slow=SLOW_PERIODS)
    cortex.addanalyzer(Returns)
    cortex.addanalyzer(TradeAnalyzer)

    print("Optimizing SMA crossover on AAPL...")
    print("  Fast periods: {}".format(FAST_PERIODS))
    print("  Slow periods: {}".format(SLOW_PERIODS))
    print("  Total combinations: {}".format(len(FAST_PERIODS) * len(SLOW_PERIODS)))
    print()

    results = cortex.run()

    # Extract and sort by total return.
    ranked = []
    for opt in results:
        ret_analysis = opt.analyzers.get("Returns", {})
        rtot = getattr(ret_analysis, "rtot", 0.0) if hasattr(ret_analysis, "rtot") else ret_analysis.get("rtot", 0.0)
        trade_analysis = opt.analyzers.get("TradeAnalyzer", {})
        total_trades = getattr(trade_analysis.total, "total", 0) if hasattr(trade_analysis, "total") else 0
        ranked.append((opt.params, rtot, total_trades))

    ranked.sort(key=lambda x: x[1], reverse=True)

    print("--- Top {} Parameter Combinations by Return ---".format(TOP_N))
    print("{:<8} {:<8} {:>12} {:>12}".format("Fast", "Slow", "Return", "Trades"))
    print("-" * 44)
    for params, rtot, trades in ranked[:TOP_N]:
        print("{:<8} {:<8} {:>11.2%} {:>12}".format(
            params.get("fast", "?"),
            params.get("slow", "?"),
            rtot,
            trades,
        ))

    print()
    best = ranked[0]
    print("Best: fast={}, slow={} -> {:.2%} return".format(
        best[0].get("fast"), best[0].get("slow"), best[1],
    ))


if __name__ == "__main__":
    main()
