"""Position tracking for the bucktrader framework.

A Position represents the current holdings of a data feed: how many units
are held (long/short/flat) and the average entry price.
"""

from __future__ import annotations

from datetime import datetime


class Position:
    """Tracks the current holdings for a single data feed.

    Attributes:
        size: Number of units held (positive=long, negative=short, 0=flat).
        price: Weighted-average entry price.
        adjbase: Last adjustment price, used for futures mark-to-market.
        datetime: Datetime of the most recent update.
    """

    def __init__(
        self,
        size: float = 0.0,
        price: float = 0.0,
        adjbase: float | None = None,
    ):
        self.size = size
        self.price = price
        self.adjbase = adjbase if adjbase is not None else price
        self.datetime: datetime | None = None

    @property
    def is_long(self) -> bool:
        return self.size > 0

    @property
    def is_short(self) -> bool:
        return self.size < 0

    @property
    def is_flat(self) -> bool:
        return self.size == 0

    def update(
        self,
        size: float,
        price: float,
        dt: datetime | None = None,
    ) -> tuple[float, float, float]:
        """Apply a trade to this position.

        Returns:
            A tuple of (opened_size, closed_size, pnl) describing the effect:
            - opened_size: units that opened new exposure.
            - closed_size: units that closed existing exposure.
            - pnl: gross profit/loss from the closed portion.

        Update logic:
            - Opening or adding: weighted-average price.
            - Reducing: price stays the same (FIFO-like).
            - Reversing: close old position, open new at trade price.
        """
        self.datetime = dt

        old_size = self.size
        new_size = old_size + size

        # Determine how much is closing vs opening.
        if old_size == 0:
            # Flat -> opening.
            opened = size
            closed = 0.0
        elif _same_sign(old_size, size):
            # Adding to existing position.
            opened = size
            closed = 0.0
        elif abs(size) <= abs(old_size):
            # Reducing position (partial or full close).
            opened = 0.0
            closed = size
        else:
            # Reversing: close old, open remainder.
            closed = -old_size
            opened = size + old_size  # remainder after closing

        # P&L from closed portion.
        pnl = 0.0
        if closed != 0.0:
            pnl = -closed * (price - self.price)

        # Update average price.
        if new_size == 0:
            # Fully closed.
            pass  # price stays as-is for reference
        elif old_size == 0 or not _same_sign(old_size, new_size):
            # New position (from flat) or reversal.
            self.price = price
        elif _same_sign(old_size, size):
            # Adding to position: weighted average.
            self.price = (
                self.price * abs(old_size) + price * abs(size)
            ) / abs(new_size)
        # else: reducing -- price stays the same.

        self.size = new_size
        self.adjbase = price

        return opened, closed, pnl

    def __repr__(self) -> str:
        return f"Position(size={self.size}, price={self.price})"

    def __bool__(self) -> bool:
        """A position is truthy when it is not flat."""
        return self.size != 0


def _same_sign(a: float, b: float) -> bool:
    """Return True if a and b have the same sign (both positive or both negative)."""
    return (a > 0 and b > 0) or (a < 0 and b < 0)
