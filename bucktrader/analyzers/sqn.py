"""SQN (System Quality Number) analyzer.

SQN = sqrt(N) * mean(pnls) / std(pnls)

Where N is the number of closed trades and pnls are the net P&L
values for each trade.
"""

from __future__ import annotations

import math
from typing import Any

from bucktrader.analyzer import Analyzer


class SQN(Analyzer):
    """System Quality Number analyzer.

    Collects trade PnL values via notify_trade() and computes
    the SQN at stop().

    Results:
        rets.sqn   -- the SQN value
        rets.trades -- number of trades used
    """

    def __init__(self, strategy: Any = None) -> None:
        super().__init__(strategy)
        self._pnls: list[float] = []

    def notify_trade(self, trade: Any) -> None:
        """Record the net PnL when a trade closes."""
        if getattr(trade, "isclosed", False):
            pnl = getattr(trade, "pnlcomm", getattr(trade, "pnl", 0.0))
            self._pnls.append(pnl)

    def stop(self) -> None:
        n = len(self._pnls)
        self.rets.trades = n

        if n < 2:
            self.rets.sqn = 0.0
            return

        mean_pnl = sum(self._pnls) / n
        variance = sum((p - mean_pnl) ** 2 for p in self._pnls) / (n - 1)
        std_pnl = math.sqrt(variance)

        if std_pnl == 0:
            self.rets.sqn = 0.0
            return

        self.rets.sqn = math.sqrt(n) * mean_pnl / std_pnl
