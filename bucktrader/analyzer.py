"""Analyzer base classes for performance metrics collection.

Analyzers collect statistics during a backtest. They do NOT produce lines --
they store results in an ordered map (AutoOrderedDict) accessible via ``rets``.

Classes:
    AutoOrderedDict  -- OrderedDict with dot-notation and auto-nesting.
    Analyzer         -- Base analyzer with lifecycle hooks and notifications.
    TimeFrameAnalyzerBase -- Analyzer with period-boundary tracking.
"""

from __future__ import annotations

import math
from collections import OrderedDict
from datetime import datetime
from typing import Any

from bucktrader.dataseries import TimeFrame


# ---------------------------------------------------------------------------
# AutoOrderedDict -- OrderedDict with dot-notation and auto-nesting
# ---------------------------------------------------------------------------


class AutoOrderedDict(OrderedDict):
    """OrderedDict that supports dot-notation access and auto-creates nested dicts.

    Accessing a missing key returns a new AutoOrderedDict, allowing deep
    assignment without explicit initialization:

        d = AutoOrderedDict()
        d.trades.won = 5
        d.trades.lost = 3
        # d == {'trades': {'won': 5, 'lost': 3}}

    Iteration skips auto-created but empty children.
    """

    _MARKER = object()

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        try:
            return self[name]
        except KeyError:
            # Auto-create a nested AutoOrderedDict for the missing key.
            child = AutoOrderedDict()
            self[name] = child
            return child

    def __setattr__(self, name: str, value: Any) -> None:
        if name.startswith("_"):
            object.__setattr__(self, name, value)
        else:
            self[name] = value

    def __delattr__(self, name: str) -> None:
        try:
            del self[name]
        except KeyError:
            raise AttributeError(name)

    def to_dict(self) -> dict:
        """Recursively convert to a plain dict (for serialization)."""
        result = {}
        for key, value in self.items():
            if isinstance(value, AutoOrderedDict):
                converted = value.to_dict()
                # Only include if it has content.
                if converted:
                    result[key] = converted
            else:
                result[key] = value
        return result

    def __repr__(self) -> str:
        items = ", ".join(f"{k!r}: {v!r}" for k, v in self.items())
        return f"AutoOrderedDict({{{items}}})"

    def _is_empty(self) -> bool:
        """Return True if this dict contains no real (non-empty-child) values."""
        for value in self.values():
            if isinstance(value, AutoOrderedDict):
                if not value._is_empty():
                    return False
            else:
                return False
        return True


# ---------------------------------------------------------------------------
# Analyzer -- Base class for all analyzers
# ---------------------------------------------------------------------------


class Analyzer:
    """Base class for performance analyzers.

    Analyzers are attached to a strategy and called at each bar. They
    accumulate statistics in ``self.rets`` (an AutoOrderedDict) and expose
    the results via ``get_analysis()``.

    Constructor:
        strategy -- the Strategy instance this analyzer is attached to.

    Lifecycle (called by the engine):
        start()                    -- once before first bar
        prenext()                  -- each warmup bar
        next()                     -- each bar after warmup
        stop()                     -- once after last bar

    Notifications (forwarded from strategy):
        notify_order(order)
        notify_trade(trade)
        notify_cashvalue(cash, value)
        notify_fund(cash, value, fundvalue, shares)
    """

    def __init__(self, strategy: Any = None) -> None:
        self.strategy = strategy
        self.rets = AutoOrderedDict()

        # Convenience references mirroring the strategy's data environment.
        if strategy is not None:
            self.datas = getattr(strategy, "datas", [])
            self.data = getattr(strategy, "data", None)
        else:
            self.datas = []
            self.data = None

        # Child analyzers for nesting.
        self._children: list[Analyzer] = []

    # -- Lifecycle hooks (override in subclasses) --------------------------

    def start(self) -> None:
        """Called once before the first bar."""

    def prenext(self) -> None:
        """Called during warmup bars (before minimum period is met)."""

    def next(self) -> None:
        """Called for each bar after warmup."""

    def stop(self) -> None:
        """Called once after the last bar. Finalize calculations here."""

    # -- Notification hooks (override in subclasses) -----------------------

    def notify_order(self, order: Any) -> None:
        """Called when an order's status changes."""

    def notify_trade(self, trade: Any) -> None:
        """Called when a trade opens or closes."""

    def notify_cashvalue(self, cash: float, value: float) -> None:
        """Called with portfolio cash and total value updates."""

    def notify_fund(
        self,
        cash: float,
        value: float,
        fundvalue: float,
        shares: float,
    ) -> None:
        """Called with fund-mode portfolio updates."""

    # -- Results access ----------------------------------------------------

    def get_analysis(self) -> AutoOrderedDict:
        """Return the results map."""
        return self.rets

    # -- Printing ----------------------------------------------------------

    def print(self, indent: int = 0, header: bool = True) -> None:
        """Print a formatted summary of analyzer results."""
        prefix = " " * indent
        if header:
            print(f"{prefix}{type(self).__name__}:")
        _print_dict(self.rets, indent=indent + 2)

    # -- Child analyzer support --------------------------------------------

    def add_child(self, child: Analyzer) -> None:
        """Register a child analyzer."""
        self._children.append(child)

    @property
    def broker(self) -> Any:
        """Convenience access to the strategy's broker."""
        if self.strategy is not None:
            return getattr(self.strategy, "broker", None)
        return None


def _print_dict(d: dict, indent: int = 0) -> None:
    """Recursively print a dict with indentation."""
    prefix = " " * indent
    for key, value in d.items():
        if isinstance(value, dict):
            if value:
                print(f"{prefix}{key}:")
                _print_dict(value, indent=indent + 2)
        else:
            print(f"{prefix}{key}: {value}")


# ---------------------------------------------------------------------------
# TimeFrameAnalyzerBase -- Period-boundary tracking analyzer
# ---------------------------------------------------------------------------

# Annualization factors: how many periods of this type fit in a year.
_ANNUALIZATION_FACTORS = {
    TimeFrame.Days: 252,
    TimeFrame.Weeks: 52,
    TimeFrame.Months: 12,
    TimeFrame.Years: 1,
}


class TimeFrameAnalyzerBase(Analyzer):
    """Analyzer base with time-period boundary detection.

    Subclasses override ``on_dt_over(dtkey)`` to handle period transitions
    and ``get_period_return()`` to compute per-period values.

    Params:
        timeframe   -- aggregation timeframe (default: TimeFrame.Years)
        compression -- timeframe compression (default: 1)
    """

    # Default params (subclasses may override).
    params = (
        ("timeframe", TimeFrame.Years),
        ("compression", 1),
    )

    def __init__(self, strategy: Any = None, **kwargs: Any) -> None:
        super().__init__(strategy)

        # Process params from class-level declaration and kwargs.
        self._params: dict[str, Any] = {}
        for name, default in self.__class__.params:
            self._params[name] = kwargs.pop(name, default)

        self.timeframe = self._params["timeframe"]
        self.compression = self._params["compression"]

        self.dtkey: datetime | None = None
        self._last_dt: datetime | None = None

    @property
    def p(self) -> _ParamAccessor:
        return _ParamAccessor(self._params)

    def _get_dt(self) -> datetime | None:
        """Extract the current datetime from the data feed."""
        if self.data is None:
            return None
        dt_line = getattr(self.data, "datetime", None)
        if dt_line is None:
            return None
        if isinstance(dt_line, datetime):
            return dt_line
        # If it is a line buffer, get current value and convert.
        if callable(getattr(dt_line, "__getitem__", None)):
            try:
                from bucktrader.dataseries import num2date
                val = float(dt_line[0])
                if not math.isnan(val):
                    return num2date(val)
            except (IndexError, TypeError, ValueError):
                pass
        return None

    def _get_dtkey(self, dt: datetime) -> datetime:
        """Convert a datetime to a period key based on the timeframe."""
        tf = self.timeframe
        if tf == TimeFrame.Years:
            return datetime(dt.year, 12, 31)
        elif tf == TimeFrame.Months:
            return datetime(dt.year, dt.month, 1)
        elif tf == TimeFrame.Weeks:
            # Use Monday of the week.
            import calendar
            weekday = dt.weekday()
            monday = dt.replace(hour=0, minute=0, second=0, microsecond=0)
            from datetime import timedelta
            monday -= timedelta(days=weekday)
            return monday
        elif tf == TimeFrame.Days:
            return datetime(dt.year, dt.month, dt.day)
        else:
            return dt

    def next(self) -> None:
        """Check for period boundary and dispatch."""
        dt = self._get_dt()
        if dt is None:
            return

        new_key = self._get_dtkey(dt)

        if self.dtkey is not None and new_key != self.dtkey:
            self.on_dt_over(self.dtkey)

        self.dtkey = new_key
        self._last_dt = dt

    def stop(self) -> None:
        """Flush the last period."""
        if self.dtkey is not None:
            self.on_dt_over(self.dtkey)

    def on_dt_over(self, dtkey: datetime) -> None:
        """Called when a time period boundary is crossed.

        Override in subclasses to record period-level metrics.
        """


class _ParamAccessor:
    """Lightweight attribute proxy for a params dict."""

    def __init__(self, params: dict[str, Any]) -> None:
        object.__setattr__(self, "_params", params)

    def __getattr__(self, name: str) -> Any:
        params = object.__getattribute__(self, "_params")
        try:
            return params[name]
        except KeyError:
            raise AttributeError(f"No parameter '{name}'")
