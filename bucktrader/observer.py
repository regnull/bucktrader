"""Observer base class for real-time monitoring.

Observers are special indicator-like components that produce lines for
visualization. They always run in event-driven mode (_nextforce=True),
meaning they execute even during warmup bars.

Observers track strategy/broker state and record it into lines that
can be plotted on charts.
"""

from __future__ import annotations

import math
from typing import Any

from bucktrader.dataseries import LineBuffer


NaN = float("nan")


class Observer:
    """Base class for all observers.

    Observers produce named lines (similar to indicators) and have
    access to the strategy and broker.

    Subclasses declare ``lines`` as a tuple of line names and override
    ``next()`` to fill line values each bar.

    Attributes:
        _nextforce  -- True: always run, even during warmup.
        _ltype      -- Component type constant (ObsType = 2).
        strategy    -- reference to the owning strategy.
        lines       -- dict of line name -> LineBuffer.
    """

    # Observer-specific flags.
    _nextforce: bool = True
    _ltype: int = 2  # ObsType

    # Subclasses override this with their line names.
    _line_names: tuple[str, ...] = ()

    def __init__(self, strategy: Any = None) -> None:
        self.strategy = strategy
        self._owner = strategy

        # Create line buffers for each declared line.
        self.lines = _ObserverLines(self._line_names)

        # Convenience: set named attributes for each line.
        for name in self._line_names:
            # Don't shadow class-level descriptors; use lines dict.
            pass

        # Minimum period.
        self._minperiod: int = 1

        # Pending order tracking for subclasses that need it.
        self._pending_orders: list[Any] = []

    @property
    def broker(self) -> Any:
        """Convenience access to the broker."""
        if self.strategy is not None:
            return getattr(self.strategy, "broker", None)
        return None

    @property
    def data(self) -> Any:
        """Convenience access to the first data feed."""
        if self.strategy is not None:
            return getattr(self.strategy, "data", None)
        return None

    @property
    def datas(self) -> list:
        """Convenience access to all data feeds."""
        if self.strategy is not None:
            return getattr(self.strategy, "datas", [])
        return []

    # -- Lifecycle hooks ---------------------------------------------------

    def start(self) -> None:
        """Called once before the first bar."""

    def prenext(self) -> None:
        """Called during warmup. Observers run next() even here."""
        self.next()

    def next(self) -> None:
        """Called each bar. Override to fill line values."""

    def stop(self) -> None:
        """Called once after the last bar."""

    # -- Notification hooks ------------------------------------------------

    def notify_order(self, order: Any) -> None:
        """Called when an order's status changes."""

    def notify_trade(self, trade: Any) -> None:
        """Called when a trade state changes."""

    # -- Line management ---------------------------------------------------

    def forward(self) -> None:
        """Advance all line buffers by one bar."""
        for name in self._line_names:
            self.lines[name].forward()

    def __repr__(self) -> str:
        return f"<{type(self).__name__} lines={self._line_names}>"


class _ObserverLines:
    """Container for observer line buffers with attribute-style access."""

    def __init__(self, line_names: tuple[str, ...]) -> None:
        self._names = line_names
        self._buffers: dict[str, LineBuffer] = {}
        for name in line_names:
            self._buffers[name] = LineBuffer(name=name)

    def __getattr__(self, name: str) -> LineBuffer:
        if name.startswith("_"):
            raise AttributeError(name)
        buffers = object.__getattribute__(self, "_buffers")
        if name in buffers:
            return buffers[name]
        raise AttributeError(f"No line '{name}'")

    def __getitem__(self, key: str) -> LineBuffer:
        return self._buffers[key]

    def __iter__(self):
        return iter(self._buffers.values())

    def __len__(self) -> int:
        return len(self._buffers)
