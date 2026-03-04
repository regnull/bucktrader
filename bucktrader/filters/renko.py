"""Renko filter -- converts OHLC bars to Renko bricks.

A Renko chart ignores time and only plots price movement. A new brick
is drawn when price moves by at least *brick_size* from the close of
the last brick.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from bucktrader.feed import BarTuple, DataBase


class Renko:
    """Filter that converts bars to Renko bricks.

    Parameters:
        brick_size: minimum price movement for a new brick.

    The filter consumes every input bar and pushes Renko bricks onto
    the data feed's stack whenever a price threshold is crossed.
    Multiple bricks may be generated from a single input bar.
    """

    def __init__(
        self,
        data: "DataBase",
        brick_size: float = 1.0,
    ) -> None:
        if brick_size <= 0:
            raise ValueError("brick_size must be positive")
        self._brick_size = brick_size
        self._last_brick_close: Optional[float] = None

    def __call__(self, data: "DataBase") -> bool:
        """Process a bar and emit Renko bricks as needed."""
        close = data.close[0]
        dt_val = data.datetime[0]

        if math.isnan(close):
            return True  # skip invalid

        if self._last_brick_close is None:
            # First bar: establish the baseline.
            self._last_brick_close = close
            return True  # consume; no brick yet

        diff = close - self._last_brick_close
        bricks = int(abs(diff) / self._brick_size)

        if bricks == 0:
            return True  # not enough movement; consume

        direction = 1.0 if diff > 0 else -1.0

        for i in range(bricks):
            brick_open = self._last_brick_close
            brick_close = brick_open + direction * self._brick_size
            brick_high = max(brick_open, brick_close)
            brick_low = min(brick_open, brick_close)

            brick: "BarTuple" = (
                dt_val,
                brick_open,
                brick_high,
                brick_low,
                brick_close,
                data.volume[0] / bricks if bricks > 0 else 0.0,
                data.openinterest[0],
            )
            data._add2stack(brick)
            self._last_brick_close = brick_close

        return True  # consume the original bar

    def last(self, data: "DataBase") -> None:
        pass
