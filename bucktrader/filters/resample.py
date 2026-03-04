"""Resampler filter -- aggregates bars into larger timeframes.

Example: aggregate 1-minute bars into 5-minute bars.

The resampler accumulates bars within a timeframe boundary, tracking
running high/low/volume, and delivers an aggregated bar when the
boundary is crossed.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Optional

from bucktrader.dataseries import OHLC_LINES, TimeFrame, date2num, num2date

if TYPE_CHECKING:
    from bucktrader.feed import BarTuple, DataBase

# ── Boundary helpers ─────────────────────────────────────────────────────────


def _timeframe_boundary(dt_num: float, timeframe: TimeFrame, compression: int) -> int:
    """Return an integer boundary key for the given datetime value.

    All bars with the same key belong to the same resampled bar.
    """
    dt = num2date(dt_num)

    if timeframe == TimeFrame.Years:
        return dt.year // compression

    if timeframe == TimeFrame.Months:
        return (dt.year * 12 + (dt.month - 1)) // compression

    if timeframe == TimeFrame.Weeks:
        # ISO week number bucketed by compression.
        iso_year, iso_week, _ = dt.isocalendar()
        return (iso_year * 53 + iso_week) // compression

    if timeframe == TimeFrame.Days:
        # Days since epoch bucketed by compression.
        return int(dt_num) // compression

    if timeframe == TimeFrame.Minutes:
        minutes_since_midnight = dt.hour * 60 + dt.minute
        day_key = int(dt_num)
        return day_key * 1440 + minutes_since_midnight // compression

    if timeframe == TimeFrame.Seconds:
        secs = dt.hour * 3600 + dt.minute * 60 + dt.second
        day_key = int(dt_num)
        return day_key * 86400 + secs // compression

    # Fallback: treat each bar as its own boundary.
    return int(dt_num * 1e6)


# ── Resampler ────────────────────────────────────────────────────────────────


class Resampler:
    """Filter that aggregates bars into a larger timeframe.

    Tracks running open/high/low/close/volume across bars that share the
    same boundary key, then pushes the completed aggregate bar onto the
    data feed's stack when the boundary changes.
    """

    def __init__(
        self,
        data: "DataBase",
        timeframe: TimeFrame = TimeFrame.Days,
        compression: int = 1,
    ) -> None:
        self._timeframe = timeframe
        self._compression = compression

        # Running aggregation state.
        self._bar_open: float = math.nan
        self._bar_high: float = -math.inf
        self._bar_low: float = math.inf
        self._bar_close: float = math.nan
        self._bar_volume: float = 0.0
        self._bar_oi: float = 0.0
        self._bar_dt: float = math.nan  # datetime of the first tick
        self._current_key: Optional[int] = None

    def _reset(self) -> None:
        self._bar_open = math.nan
        self._bar_high = -math.inf
        self._bar_low = math.inf
        self._bar_close = math.nan
        self._bar_volume = 0.0
        self._bar_oi = 0.0
        self._bar_dt = math.nan
        self._current_key = None

    def _snapshot(self) -> "BarTuple":
        """Return the aggregated bar as a tuple."""
        return (
            self._bar_dt,
            self._bar_open,
            self._bar_high,
            self._bar_low,
            self._bar_close,
            self._bar_volume,
            self._bar_oi,
        )

    def _accumulate(self, data: "DataBase") -> None:
        """Fold the current bar of *data* into the running aggregate."""
        o = data.open[0]
        h = data.high[0]
        low = data.low[0]
        c = data.close[0]
        v = data.volume[0]
        oi = data.openinterest[0]

        if math.isnan(self._bar_open):
            self._bar_open = o
            self._bar_dt = data.datetime[0]
        if h > self._bar_high:
            self._bar_high = h
        if low < self._bar_low:
            self._bar_low = low
        self._bar_close = c
        if not math.isnan(v):
            self._bar_volume += v
        if not math.isnan(oi):
            self._bar_oi = oi

    # ── filter interface ─────────────────────────────────────────────────

    def __call__(self, data: "DataBase") -> bool:
        """Process one bar. Return True to consume it, False to deliver."""
        dt_val = data.datetime[0]
        if math.isnan(dt_val):
            return True  # skip invalid bars

        key = _timeframe_boundary(dt_val, self._timeframe, self._compression)

        if self._current_key is None:
            # First bar -- just start accumulating.
            self._current_key = key
            self._accumulate(data)
            return True  # consume the raw bar

        if key == self._current_key:
            # Same boundary -- keep accumulating.
            self._accumulate(data)
            return True

        # Boundary crossed: deliver the completed bar and start new period.
        completed = self._snapshot()
        data._add2stack(completed)
        self._reset()
        self._current_key = key
        self._accumulate(data)
        return True  # consume the raw bar; completed goes via stack

    def last(self, data: "DataBase") -> None:
        """Flush any remaining accumulated bar when data is exhausted."""
        if self._current_key is not None and not math.isnan(self._bar_open):
            completed = self._snapshot()
            data._add2stack(completed)
            self._reset()
