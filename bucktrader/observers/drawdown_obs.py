"""DrawDown observer -- tracks current and maximum drawdown.

Lines:
    drawdown    -- current drawdown percentage
    maxdrawdown -- maximum drawdown percentage seen so far
"""

from __future__ import annotations

from typing import Any

from bucktrader.observer import Observer


class DrawDown(Observer):
    """Observer that records current and maximum drawdown each bar."""

    _line_names = ("drawdown", "maxdrawdown")

    def __init__(self, strategy: Any = None) -> None:
        super().__init__(strategy)
        self._peak: float = 0.0
        self._max_dd: float = 0.0

    def start(self) -> None:
        if self.broker is not None:
            self._peak = self.broker.getvalue()

    def next(self) -> None:
        if self.broker is None:
            return

        value = self.broker.getvalue()

        if value >= self._peak:
            self._peak = value

        if self._peak != 0:
            dd = ((self._peak - value) / self._peak) * 100.0
        else:
            dd = 0.0

        if dd > self._max_dd:
            self._max_dd = dd

        self.lines.drawdown[0] = dd
        self.lines.maxdrawdown[0] = self._max_dd
