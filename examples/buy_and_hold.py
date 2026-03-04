"""Buy and Hold strategy example.

Buys AAPL on the first bar and holds until the end of the backtest.
Demonstrates: GenericCSVData loading, basic strategy, analyzers.
"""

from pathlib import Path

from bucktrader.analyzers import DrawDown, Returns
from bucktrader.cortex import Cortex
from bucktrader.feed import GenericCSVData
from bucktrader.strategy import Strategy

DATA_DIR = Path(__file__).parent / "data"


class BuyAndHold(Strategy):
    """Buy once on the first bar and hold forever."""

    def __init__(self):
        super().__init__()
        self._entered = False

    def _next(self):
        if not self._entered:
            self.buy(size=10)
            self._entered = True


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
    cortex.addstrategy(BuyAndHold)
    cortex.addanalyzer(Returns)
    cortex.addanalyzer(DrawDown)

    print("Starting portfolio value: ${:.2f}".format(cortex.broker.getcash()))
    results = cortex.run()
    strat = results[0]

    final_value = cortex.broker.getvalue()
    print("Final portfolio value:    ${:.2f}".format(final_value))

    returns = strat._analyzers[0].get_analysis()
    drawdown = strat._analyzers[1].get_analysis()

    print("\n--- Performance ---")
    print("Total return:       {:.2%}".format(returns.rtot))
    print("Average bar return: {:.4%}".format(returns.ravg))
    print("\n--- Drawdown ---")
    print("Max drawdown:       {:.2f}%".format(drawdown.max.drawdown))
    print("Max money down:     ${:.2f}".format(drawdown.max.moneydown))
    print("Max duration:       {} bars".format(drawdown.max.len))


if __name__ == "__main__":
    main()
