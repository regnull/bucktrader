"""CalendarDays filter -- adds bars for missing calendar days.

When the data feed has gaps (e.g., weekends), this filter inserts
synthetic bars so that every calendar day has a bar. The synthetic
bars repeat the previous close as OHLC with zero volume.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Optional

from bucktrader.dataseries import date2num, num2date

if TYPE_CHECKING:
    from bucktrader.feed import BarTuple, DataBase


class CalendarDays:
    """Fill in missing calendar days between consecutive bars.

    Synthetic bars carry the previous bar's close as all OHLC values,
    zero volume, and zero open interest.
    """

    def __init__(self, data: "DataBase") -> None:
        self._last_dt: Optional[float] = None
        self._last_close: float = math.nan
        self._last_oi: float = 0.0

    def __call__(self, data: "DataBase") -> bool:
        dt_val = data.datetime[0]
        if math.isnan(dt_val):
            return True  # skip invalid

        if self._last_dt is not None:
            # Compute calendar day gap.
            prev_day = int(self._last_dt)
            curr_day = int(dt_val)
            gap = curr_day - prev_day

            if gap > 1 and not math.isnan(self._last_close):
                # Insert synthetic bars for each missing day.
                for d in range(1, gap):
                    fill_dt = float(prev_day + d)
                    fill_bar: "BarTuple" = (
                        fill_dt,
                        self._last_close,
                        self._last_close,
                        self._last_close,
                        self._last_close,
                        0.0,
                        self._last_oi,
                    )
                    data._add2stack(fill_bar)

        self._last_dt = dt_val
        self._last_close = data.close[0]
        self._last_oi = data.openinterest[0] if not math.isnan(data.openinterest[0]) else 0.0

        return False  # keep the current bar

    def last(self, data: "DataBase") -> None:
        pass
