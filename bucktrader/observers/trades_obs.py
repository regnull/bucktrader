"""Trades observer -- tracks completed trade P&L.

Lines:
    pnlplus  -- positive P&L (profit) from closed trades (NaN otherwise)
    pnlminus -- negative P&L (loss) from closed trades (NaN otherwise)
"""

from __future__ import annotations

import math
from typing import Any

from bucktrader.observer import Observer


NaN = float("nan")


class Trades(Observer):
    """Observer that plots trade P&L: profits above, losses below."""

    _line_names = ("pnlplus", "pnlminus")

    def __init__(self, strategy: Any = None) -> None:
        super().__init__(strategy)
        self._closed_trades: list[Any] = []

    def notify_trade(self, trade: Any) -> None:
        """Track closed trades for P&L plotting."""
        if getattr(trade, "isclosed", False):
            self._closed_trades.append(trade)

    def next(self) -> None:
        pnlplus = NaN
        pnlminus = NaN

        for trade in self._closed_trades:
            pnl = getattr(trade, "pnlcomm", getattr(trade, "pnl", 0.0))
            if pnl >= 0:
                pnlplus = pnl
            else:
                pnlminus = pnl

        self.lines.pnlplus[0] = pnlplus
        self.lines.pnlminus[0] = pnlminus

        self._closed_trades.clear()
