"""Multi-data portfolio strategy example.

Trades AAPL, MSFT, and SPY simultaneously using a simple SMA filter
on each instrument. Demonstrates: multiple data feeds, per-data
position management, iterating over all feeds in a strategy.
"""

from pathlib import Path

from bucktrader.analyzers import DrawDown, Returns, TradeAnalyzer
from bucktrader.cortex import Cortex
from bucktrader.feed import GenericCSVData
from bucktrader.indicators import SMA
from bucktrader.strategy import Strategy

DATA_DIR = Path(__file__).parent / "data"

SMA_PERIOD = 20
TRADE_SIZE = 5


def _data_name(data):
    """Get the display name for a data feed."""
    return getattr(data, "p_name", None) or getattr(data, "_name", "?")


def _load_csv(filename):
    return GenericCSVData(
        dataname=DATA_DIR / filename,
        dtformat="%Y-%m-%d",
        open_col=1,
        high_col=2,
        low_col=3,
        close_col=4,
        volume_col=5,
        openinterest_col=6,
    )


class MultiDataSma(Strategy):
    """Buy each instrument when price is above its SMA, sell when below."""

    params = (
        ("period", SMA_PERIOD),
        ("size", TRADE_SIZE),
    )

    def start(self):
        self._indicators = {}
        self._bars = 0
        for data in self.datas:
            sma = SMA(data.close, period=self.p.period)
            name = _data_name(data)
            self._indicators[name] = sma

    def _next(self):
        self._bars += 1

        # Step all indicators.
        for sma in self._indicators.values():
            sma.lines.forward()
            sma.next()

        # Wait for SMA warmup.
        if self._bars < self.p.period:
            return

        for data in self.datas:
            name = _data_name(data)
            sma = self._indicators[name]
            price = data.close[0]
            sma_val = sma.lines.av[0]
            pos = self.getposition(data)

            if pos.size == 0 and price > sma_val:
                self.buy(data=data, size=self.p.size)
            elif pos.size > 0 and price < sma_val:
                self.close(data=data)


def main():
    cortex = Cortex(preload=False, runonce=False, stdstats=False)

    for name, filename in [("AAPL", "aapl.csv"), ("MSFT", "msft.csv"), ("SPY", "spy.csv")]:
        cortex.adddata(_load_csv(filename), name=name)

    cortex.addstrategy(MultiDataSma)
    cortex.addanalyzer(Returns)
    cortex.addanalyzer(TradeAnalyzer)
    cortex.addanalyzer(DrawDown)

    print("Starting portfolio value: ${:.2f}".format(cortex.broker.getcash()))
    results = cortex.run()
    strat = results[0]

    final_value = cortex.broker.getvalue()
    print("Final portfolio value:    ${:.2f}".format(final_value))

    returns = strat._analyzers[0].get_analysis()
    trades = strat._analyzers[1].get_analysis()
    drawdown = strat._analyzers[2].get_analysis()

    print("\n--- Returns ---")
    print("Total return: {:.2%}".format(returns.rtot))

    print("\n--- Trade Statistics ---")
    print("Total trades: {}".format(trades.total.total))
    print("  Won:        {}".format(trades.won.total))
    print("  Lost:       {}".format(trades.lost.total))
    print("Net P&L:      ${:.2f}".format(trades.pnl.net.total))

    print("\n--- Drawdown ---")
    print("Max drawdown:   {:.2f}%".format(drawdown.max.drawdown))
    print("Max money down: ${:.2f}".format(drawdown.max.moneydown))

    # Per-instrument positions at end.
    print("\n--- Final Positions ---")
    for data in strat.datas:
        name = _data_name(data)
        pos = strat.getposition(data)
        print("  {}: {} shares".format(name, pos.size))


if __name__ == "__main__":
    main()
