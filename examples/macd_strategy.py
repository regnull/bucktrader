"""MACD Histogram strategy example.

Trades SPY based on MACD histogram zero-crossings: buy when the
histogram turns positive, sell when it turns negative.
Demonstrates: MACDHisto indicator, SharpeRatio analyzer.
"""

from pathlib import Path

from bucktrader.analyzers import Returns, SharpeRatio, TradeAnalyzer
from bucktrader.cortex import Cortex
from bucktrader.feed import GenericCSVData
from bucktrader.indicators import MACDHisto
from bucktrader.strategy import Strategy

DATA_DIR = Path(__file__).parent / "data"

FAST_PERIOD = 12
SLOW_PERIOD = 26
SIGNAL_PERIOD = 9
TRADE_SIZE = 10


class MacdHistoStrategy(Strategy):
    """Buy when MACD histogram crosses above zero, sell when it crosses below."""

    params = (
        ("fast", FAST_PERIOD),
        ("slow", SLOW_PERIOD),
        ("signal", SIGNAL_PERIOD),
        ("size", TRADE_SIZE),
    )

    def start(self):
        self.macd = MACDHisto(
            self.data.close,
            period_me1=self.p.fast,
            period_me2=self.p.slow,
            period_signal=self.p.signal,
        )
        self._bar = 0
        self._prev_histo = 0.0

    def _next(self):
        self._bar += 1

        # Step the MACD indicator.
        self.macd.lines.forward()
        self.macd.next()

        # Wait for MACD warmup (slow EMA period + signal period).
        warmup = self.p.slow + self.p.signal
        if self._bar < warmup:
            return

        histo = self.macd.lines.histo[0]

        # Buy on histogram crossing above zero.
        if self.position.size == 0 and self._prev_histo <= 0 and histo > 0:
            self.buy(size=self.p.size)
        # Sell on histogram crossing below zero.
        elif self.position.size > 0 and self._prev_histo >= 0 and histo < 0:
            self.close()

        self._prev_histo = histo


def main():
    data = GenericCSVData(
        dataname=DATA_DIR / "spy.csv",
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
    cortex.addstrategy(MacdHistoStrategy)
    cortex.addanalyzer(Returns)
    cortex.addanalyzer(SharpeRatio)
    cortex.addanalyzer(TradeAnalyzer)

    print("Starting portfolio value: ${:.2f}".format(cortex.broker.getcash()))
    results = cortex.run()
    strat = results[0]

    final_value = cortex.broker.getvalue()
    print("Final portfolio value:    ${:.2f}".format(final_value))

    returns = strat._analyzers[0].get_analysis()
    sharpe = strat._analyzers[1].get_analysis()
    trades = strat._analyzers[2].get_analysis()

    print("\n--- Returns ---")
    print("Total return: {:.2%}".format(returns.rtot))

    print("\n--- Sharpe Ratio ---")
    print("Sharpe: {:.4f}".format(sharpe.get("sharperatio", 0.0)))

    print("\n--- Trade Statistics ---")
    print("Total trades: {}".format(trades.total.total))
    print("  Won:        {}".format(trades.won.total))
    print("  Lost:       {}".format(trades.lost.total))
    print("Net P&L:      ${:.2f}".format(trades.pnl.net.total))
    print("Best win:     ${:.2f}".format(trades.won.pnl.max))
    print("Worst loss:   ${:.2f}".format(trades.lost.pnl.max))


if __name__ == "__main__":
    main()
