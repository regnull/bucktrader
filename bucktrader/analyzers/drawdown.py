"""DrawDown analyzer.

Tracks peak portfolio value and computes:
- Current drawdown (percentage and money)
- Maximum drawdown (percentage, money, and duration in bars)
"""

from __future__ import annotations

from typing import Any

from bucktrader.analyzer import Analyzer


class DrawDown(Analyzer):
    """DrawDown analyzer.

    Monitors the portfolio value each bar and tracks how far it has
    fallen from its peak.

    Results in ``self.rets``:
        drawdown       -- current drawdown percentage
        moneydown      -- current drawdown in money
        max.drawdown   -- maximum drawdown percentage
        max.moneydown  -- maximum drawdown in money
        max.len        -- maximum drawdown duration in bars
    """

    def __init__(self, strategy: Any = None) -> None:
        super().__init__(strategy)

        self._peak: float = 0.0
        self._drawdown: float = 0.0
        self._moneydown: float = 0.0
        self._max_drawdown: float = 0.0
        self._max_moneydown: float = 0.0

        # Duration tracking.
        self._current_len: int = 0
        self._max_len: int = 0

    def start(self) -> None:
        if self.broker is not None:
            self._peak = self.broker.getvalue()

    def next(self) -> None:
        if self.broker is None:
            return

        value = self.broker.getvalue()

        if value >= self._peak:
            self._peak = value
            self._current_len = 0
        else:
            self._current_len += 1

        # Compute current drawdown.
        if self._peak != 0:
            self._moneydown = self._peak - value
            self._drawdown = (self._moneydown / self._peak) * 100.0
        else:
            self._moneydown = 0.0
            self._drawdown = 0.0

        # Update maximums.
        if self._drawdown > self._max_drawdown:
            self._max_drawdown = self._drawdown
        if self._moneydown > self._max_moneydown:
            self._max_moneydown = self._moneydown
        if self._current_len > self._max_len:
            self._max_len = self._current_len

    def stop(self) -> None:
        r = self.rets
        r.drawdown = self._drawdown
        r.moneydown = self._moneydown
        r.max.drawdown = self._max_drawdown
        r.max.moneydown = self._max_moneydown
        r.max.len = self._max_len
