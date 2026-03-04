"""Session-related filters: SessionFilter and SessionFiller.

SessionFilter removes bars outside a trading session window.
SessionFiller inserts synthetic bars to fill gaps within sessions.
"""

from __future__ import annotations

import math
from datetime import time, timedelta
from typing import TYPE_CHECKING, Optional

from bucktrader.dataseries import date2num, num2date

if TYPE_CHECKING:
    from bucktrader.feed import BarTuple, DataBase


class SessionFilter:
    """Remove bars that fall outside the trading session window.

    Uses the data feed's ``p_sessionstart`` and ``p_sessionend`` parameters.
    If neither is set, no filtering is applied.
    """

    def __init__(self, data: "DataBase") -> None:
        self._sessionstart: Optional[time] = data.p_sessionstart
        self._sessionend: Optional[time] = data.p_sessionend

    def __call__(self, data: "DataBase") -> bool:
        """Return True to consume (remove) the bar, False to keep it."""
        if self._sessionstart is None and self._sessionend is None:
            return False

        dt_val = data.datetime[0]
        if math.isnan(dt_val):
            return True

        dt = num2date(dt_val)
        bar_time = dt.time()

        if self._sessionstart is not None and bar_time < self._sessionstart:
            return True  # before session
        if self._sessionend is not None and bar_time > self._sessionend:
            return True  # after session

        return False

    def last(self, data: "DataBase") -> None:
        pass


class SessionFiller:
    """Fill gaps within the trading session with synthetic bars.

    When a gap is detected between consecutive bars (both within the
    session), synthetic bars are injected with the previous close as
    the OHLC values and zero volume.

    The ``fill_timeframe_seconds`` parameter controls the expected bar
    interval.
    """

    def __init__(
        self,
        data: "DataBase",
        fill_timeframe_seconds: float = 60.0,
    ) -> None:
        self._sessionstart: Optional[time] = data.p_sessionstart
        self._sessionend: Optional[time] = data.p_sessionend
        self._fill_secs = fill_timeframe_seconds
        self._last_dt: Optional[float] = None
        self._last_close: float = math.nan

    def __call__(self, data: "DataBase") -> bool:
        dt_val = data.datetime[0]
        if math.isnan(dt_val):
            return True

        if self._last_dt is not None:
            gap_secs = (dt_val - self._last_dt) * 86400.0
            expected = self._fill_secs
            # Only fill when gap is larger than expected.
            if gap_secs > expected * 1.5 and not math.isnan(self._last_close):
                fill_count = int(gap_secs / expected) - 1
                # Limit fill count to avoid runaway loops.
                fill_count = min(fill_count, 1000)
                for i in range(1, fill_count + 1):
                    fill_dt = self._last_dt + (i * expected) / 86400.0
                    fill_bar = (
                        fill_dt,
                        self._last_close,
                        self._last_close,
                        self._last_close,
                        self._last_close,
                        0.0,
                        0.0,
                    )
                    data._add2stack(fill_bar)

        self._last_dt = dt_val
        self._last_close = data.close[0]
        return False  # keep the current bar

    def last(self, data: "DataBase") -> None:
        pass
