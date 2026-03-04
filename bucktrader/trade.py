"""Trade tracking for the bucktrader framework.

A Trade represents a round-trip: from entry through optional adds to exit.
It accumulates P&L, commissions, and provides a complete history of events.
"""

from __future__ import annotations

import itertools
from datetime import datetime
from enum import IntEnum
from typing import Any, NamedTuple


class TradeStatus(IntEnum):
    """Status of a trade."""

    Created = 0
    Open = 1
    Closed = 2


class TradeHistoryEntry(NamedTuple):
    """One event in a trade's history.

    Attributes:
        status: Tuple of (trade_status, size, price, value, pnl, pnlcomm).
        event: Tuple of (order_ref, size, price, commission, pnl, value).
    """

    status: tuple[Any, ...]
    event: tuple[Any, ...]


# Global auto-increment counter for unique trade references.
_trade_ref_counter = itertools.count(1)


def _next_trade_ref() -> int:
    return next(_trade_ref_counter)


def reset_trade_ref_counter(start: int = 1) -> None:
    """Reset the global trade reference counter (useful for testing)."""
    global _trade_ref_counter
    _trade_ref_counter = itertools.count(start)


class Trade:
    """Represents a round-trip trade: entry, optional adds, and exit.

    Attributes:
        ref: Unique trade reference number.
        status: Current status (Created, Open, Closed).
        data: The data feed being traded.
        tradeid: Trade group identifier.
        size: Current position size in this trade.
        price: Weighted-average entry price.
        value: Current position value.
        commission: Total commission paid.
        pnl: Gross P&L.
        pnlcomm: Net P&L (gross - commission).
        isopen: True if trade is currently open.
        isclosed: True if trade just closed this bar.
        justopened: True if trade just opened this bar.
        baropen: Bar index at open.
        barclose: Bar index at close (0 until closed).
        barlen: Duration in bars.
        dtopen: Datetime at open.
        dtclose: Datetime at close.
        history: List of TradeHistoryEntry records.
    """

    Status = TradeStatus

    def __init__(
        self,
        data: Any = None,
        tradeid: int = 0,
        historyon: bool = False,
    ):
        self.ref = _next_trade_ref()
        self.data = data
        self.tradeid = tradeid
        self.status = TradeStatus.Created

        self.size: float = 0.0
        self.price: float = 0.0
        self.value: float = 0.0
        self.commission: float = 0.0
        self.pnl: float = 0.0
        self.pnlcomm: float = 0.0

        self.justopened: bool = False
        self.isopen: bool = False
        self.isclosed: bool = False

        self.baropen: int = 0
        self.barclose: int = 0
        self.barlen: int = 0

        self.dtopen: datetime | None = None
        self.dtclose: datetime | None = None

        self.historyon = historyon
        self.history: list[TradeHistoryEntry] = []

    def update(
        self,
        order_ref: int,
        size: float,
        price: float,
        value: float,
        commission: float,
        pnl: float,
        dt: datetime | None = None,
        bar: int = 0,
    ) -> None:
        """Apply an execution to this trade.

        Args:
            order_ref: Reference of the order that caused this update.
            size: Size of this execution (positive=buy, negative=sell).
            price: Execution price.
            value: Execution value.
            commission: Commission for this execution.
            pnl: Gross P&L for this execution.
            dt: Datetime of execution.
            bar: Bar index of execution.
        """
        # Reset per-bar flags.
        self.justopened = False
        self.isclosed = False

        old_size = self.size
        new_size = old_size + size

        # Update average entry price (only for opening trades).
        if old_size == 0:
            # First entry.
            self.price = price
            self.dtopen = dt
            self.baropen = bar
            self.justopened = True
        elif _same_sign(old_size, size):
            # Adding to existing position: weighted average.
            self.price = (
                self.price * abs(old_size) + price * abs(size)
            ) / abs(new_size)
        # Reducing: price stays the same.

        self.size = new_size
        self.commission += commission
        self.pnl += pnl
        self.pnlcomm = self.pnl - self.commission
        self.value = value

        if new_size == 0:
            # Trade is closed.
            self.isclosed = True
            self.isopen = False
            self.status = TradeStatus.Closed
            self.dtclose = dt
            self.barclose = bar
            self.barlen = bar - self.baropen if bar else 0
        else:
            self.isopen = True
            self.status = TradeStatus.Open

        # Record history entry if enabled.
        if self.historyon:
            status_tuple = (
                self.status,
                self.size,
                self.price,
                self.value,
                self.pnl,
                self.pnlcomm,
            )
            event_tuple = (
                order_ref,
                size,
                price,
                commission,
                pnl,
                value,
            )
            self.history.append(TradeHistoryEntry(status_tuple, event_tuple))

    def __repr__(self) -> str:
        return (
            f"Trade(ref={self.ref}, status={self.status.name}, "
            f"size={self.size}, pnl={self.pnl:.2f})"
        )


def _same_sign(a: float, b: float) -> bool:
    """Return True if a and b have the same sign."""
    return (a > 0 and b > 0) or (a < 0 and b < 0)
