"""HeikinAshi filter -- converts standard OHLC bars to Heikin-Ashi bars.

Heikin-Ashi formulae:
    HA_Close = (Open + High + Low + Close) / 4
    HA_Open  = (prev_HA_Open + prev_HA_Close) / 2   (first bar: (O+C)/2)
    HA_High  = max(High, HA_Open, HA_Close)
    HA_Low   = min(Low, HA_Open, HA_Close)
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bucktrader.feed import DataBase


class HeikinAshi:
    """Filter that converts OHLC bars to Heikin-Ashi representation.

    The filter modifies bar values in-place. Volume, openinterest, and
    datetime are passed through unchanged.
    """

    def __init__(self, data: "DataBase") -> None:
        self._prev_ha_open: float = math.nan
        self._prev_ha_close: float = math.nan

    def __call__(self, data: "DataBase") -> bool:
        """Transform the current bar to Heikin-Ashi. Never consumes."""
        o = data.open[0]
        h = data.high[0]
        low = data.low[0]
        c = data.close[0]

        ha_close = (o + h + low + c) / 4.0

        if math.isnan(self._prev_ha_open):
            # First bar: seed with simple average.
            ha_open = (o + c) / 2.0
        else:
            ha_open = (self._prev_ha_open + self._prev_ha_close) / 2.0

        ha_high = max(h, ha_open, ha_close)
        ha_low = min(low, ha_open, ha_close)

        # Write Heikin-Ashi values back.
        data.open[0] = ha_open
        data.high[0] = ha_high
        data.low[0] = ha_low
        data.close[0] = ha_close

        self._prev_ha_open = ha_open
        self._prev_ha_close = ha_close

        return False  # keep the bar

    def last(self, data: "DataBase") -> None:
        pass
