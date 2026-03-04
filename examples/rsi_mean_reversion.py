"""RSI Mean Reversion strategy example.

Buys MSFT when RSI drops below 30 (oversold), sells when RSI rises
above 70 (overbought). Demonstrates: RSI indicator, configurable
parameters, DrawDown analyzer.
"""

from pathlib import Path

from bucktrader.analyzers import DrawDown, Returns, TradeAnalyzer
from bucktrader.cortex import Cortex
from bucktrader.feed import GenericCSVData
from bucktrader.indicators import RSI
from bucktrader.strategy import Strategy

DATA_DIR = Path(__file__).parent / "data"

RSI_PERIOD = 14
RSI_OVERSOLD = 30.0
RSI_OVERBOUGHT = 70.0
TRADE_SIZE = 10


class RsiMeanReversion(Strategy):
    """Buy on RSI oversold, sell on RSI overbought."""

    params = (
        ("period", RSI_PERIOD),
        ("oversold", RSI_OVERSOLD),
        ("overbought", RSI_OVERBOUGHT),
        ("size", TRADE_SIZE),
    )

    def start(self):
        self.rsi = RSI(self.data.close, period=self.p.period)
        self._bar = 0

    def _next(self):
        self._bar += 1

        # Step the RSI indicator.
        self.rsi.lines.forward()
        self.rsi.next()

        # Wait for RSI warmup.
        if self._bar <= self.p.period:
            return

        rsi_val = self.rsi.lines.rsi[0]

        if self.position.size == 0 and rsi_val < self.p.oversold:
            self.buy(size=self.p.size)
        elif self.position.size > 0 and rsi_val > self.p.overbought:
            self.close()


def main():
    data = GenericCSVData(
        dataname=DATA_DIR / "msft.csv",
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
    cortex.addstrategy(RsiMeanReversion)
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
    print("Avg P&L:      ${:.2f}".format(trades.pnl.net.average))

    print("\n--- Drawdown ---")
    print("Max drawdown:   {:.2f}%".format(drawdown.max.drawdown))
    print("Max money down: ${:.2f}".format(drawdown.max.moneydown))
    print("Max duration:   {} bars".format(drawdown.max.len))


if __name__ == "__main__":
    main()
