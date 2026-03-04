"""Replayer filter -- like resampler but delivers intermediate partial bars.

The replayer delivers an updated (partial) bar on every tick, so the
strategy sees the bar "building" in real time.  Uses ``backwards()``
to rewrite the previous partial bar before delivering an updated one.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Optional

from bucktrader.dataseries import TimeFrame
from bucktrader.filters.resample import _timeframe_boundary

if TYPE_CHECKING:
    from bucktrader.feed import BarTuple, DataBase


class Replayer:
    """Filter that replays bar construction with intermediate partial bars.

    On every input bar the replayer delivers an updated aggregated bar
    that reflects all ticks seen so far in the current boundary period.
    When the boundary crosses, the final bar is delivered normally and
    a new period starts.
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
        self._bar_dt: float = math.nan
        self._current_key: Optional[int] = None
        self._delivered_partial: bool = False

    def _reset(self) -> None:
        self._bar_open = math.nan
        self._bar_high = -math.inf
        self._bar_low = math.inf
        self._bar_close = math.nan
        self._bar_volume = 0.0
        self._bar_oi = 0.0
        self._bar_dt = math.nan
        self._current_key = None
        self._delivered_partial = False

    def _snapshot(self) -> "BarTuple":
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
        """Process one bar. Delivers intermediate partial bars."""
        dt_val = data.datetime[0]
        if math.isnan(dt_val):
            return True

        key = _timeframe_boundary(dt_val, self._timeframe, self._compression)

        if self._current_key is None:
            # First bar.
            self._current_key = key
            self._accumulate(data)
            # Deliver the first partial bar directly (don't consume).
            partial = self._snapshot()
            for i, val in enumerate(partial):
                data.get_line(i)[0] = val
            self._delivered_partial = True
            return False  # keep -- the bar is delivered

        if key == self._current_key:
            # Same period -- update the partial bar.
            self._accumulate(data)
            if self._delivered_partial:
                # Rewrite the previous partial: go back, then overwrite.
                data.backwards()
                data.forward()
            partial = self._snapshot()
            for i, val in enumerate(partial):
                data.get_line(i)[0] = val
            self._delivered_partial = True
            return False

        # Boundary crossed.
        # The last partial was already delivered; start new period.
        self._reset()
        self._current_key = key
        self._accumulate(data)
        partial = self._snapshot()
        for i, val in enumerate(partial):
            data.get_line(i)[0] = val
        self._delivered_partial = True
        return False

    def last(self, data: "DataBase") -> None:
        """Nothing special needed -- the last partial was already delivered."""
        pass
