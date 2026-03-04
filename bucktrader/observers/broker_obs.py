"""Broker observer -- tracks portfolio cash and total value.

Lines:
    cash  -- current cash balance
    value -- total portfolio value (cash + positions)
"""

from __future__ import annotations

from typing import Any

from bucktrader.observer import Observer


class Broker(Observer):
    """Observer that records cash and portfolio value each bar."""

    _line_names = ("cash", "value")

    def next(self) -> None:
        if self.broker is None:
            return
        self.lines.cash[0] = self.broker.getcash()
        self.lines.value[0] = self.broker.getvalue()
