"""SMA Crossover strategy example.

Classic trend-following: buy on golden cross (fast SMA > slow SMA),
sell on death cross (fast SMA < slow SMA). Uses AAPL daily data.
Demonstrates: SMA indicator, parameterized strategy, trade analysis.
"""

from pathlib import Path

from bucktrader.analyzers import Returns, SharpeRatio, TradeAnalyzer
from bucktrader.cortex import Cortex
from bucktrader.feed import GenericCSVData
from bucktrader.indicators import SMA
from bucktrader.strategy import Strategy

DATA_DIR = Path(__file__).parent / "data"

FAST_PERIOD = 10
SLOW_PERIOD = 30
TRADE_SIZE = 10


class SmaCrossover(Strategy):
    """Buy when fast SMA crosses above slow SMA, sell on the reverse."""

    params = (
        ("fast", FAST_PERIOD),
        ("slow", SLOW_PERIOD),
        ("size", TRADE_SIZE),
    )

    def start(self):
        self.fast_sma = SMA(self.data.close, period=self.p.fast)
        self.slow_sma = SMA(self.data.close, period=self.p.slow)
        self._bar = 0

    def _next(self):
        self._bar += 1

        # Step indicators.
        self.fast_sma.lines.forward()
        self.fast_sma.next()
        self.slow_sma.lines.forward()
        self.slow_sma.next()

        # Wait for enough bars.
        if self._bar < self.p.slow:
            return

        fast_val = self.fast_sma.lines.av[0]
        slow_val = self.slow_sma.lines.av[0]

        if self.position.size == 0 and fast_val > slow_val:
            self.buy(size=self.p.size)
        elif self.position.size > 0 and fast_val < slow_val:
            self.close()


def main():
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

    cortex = Cortex(preload=False, runonce=False, stdstats=False)
    cortex.adddata(data)
    cortex.addstrategy(SmaCrossover)
    cortex.addanalyzer(Returns)
    cortex.addanalyzer(TradeAnalyzer)
    cortex.addanalyzer(SharpeRatio)

    print("Starting portfolio value: ${:.2f}".format(cortex.broker.getcash()))
    results = cortex.run()
    strat = results[0]

    final_value = cortex.broker.getvalue()
    print("Final portfolio value:    ${:.2f}".format(final_value))

    returns = strat._analyzers[0].get_analysis()
    trades = strat._analyzers[1].get_analysis()
    sharpe = strat._analyzers[2].get_analysis()

    print("\n--- Returns ---")
    print("Total return: {:.2%}".format(returns.rtot))

    print("\n--- Sharpe Ratio ---")
    print("Sharpe: {:.4f}".format(sharpe.get("sharperatio", 0.0)))

    print("\n--- Trade Statistics ---")
    print("Total trades: {}".format(trades.total.total))
    print("  Open:       {}".format(trades.total.open))
    print("  Closed:     {}".format(trades.total.closed))
    print("  Won:        {}".format(trades.won.total))
    print("  Lost:       {}".format(trades.lost.total))
    print("Net P&L:      ${:.2f}".format(trades.pnl.net.total))
    print("Avg P&L:      ${:.2f}".format(trades.pnl.net.average))
    print("Best win:     ${:.2f}".format(trades.won.pnl.max))
    print("Worst loss:   ${:.2f}".format(trades.lost.pnl.max))


if __name__ == "__main__":
    main()
