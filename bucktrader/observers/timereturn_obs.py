"""TimeReturn observer."""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any

from bucktrader.dataseries import TimeFrame, num2date
from bucktrader.observer import Observer


NaN = float("nan")


class TimeReturn(Observer):
    """Observer that emits period returns on boundary changes."""

    _line_names = ("timereturn",)

    def __init__(
        self,
        strategy: Any = None,
        timeframe: TimeFrame = TimeFrame.Days,
        compression: int = 1,
    ) -> None:
        super().__init__(strategy)
        self.timeframe = timeframe
        self.compression = compression
        self._period_start_value: float | None = None
        self._period_key: datetime | None = None

    def start(self) -> None:
        if self.broker is not None:
            self._period_start_value = self.broker.getvalue()

    def next(self) -> None:
        if self.broker is None or self.data is None:
            self.lines.timereturn[0] = NaN
            return

        dt = _get_dt(self.data)
        if dt is None:
            self.lines.timereturn[0] = NaN
            return

        key = _get_dtkey(dt, self.timeframe)
        value = self.broker.getvalue()

        if self._period_key is None:
            self._period_key = key
            self._period_start_value = value
            self.lines.timereturn[0] = NaN
            return

        if key != self._period_key:
            if self._period_start_value and self._period_start_value != 0:
                self.lines.timereturn[0] = (value / self._period_start_value) - 1.0
            else:
                self.lines.timereturn[0] = NaN
            self._period_key = key
            self._period_start_value = value
            return

        self.lines.timereturn[0] = NaN


def _get_dt(data: Any) -> datetime | None:
    dt_line = getattr(data, "datetime", None)
    if dt_line is None or not callable(getattr(dt_line, "__getitem__", None)):
        return None
    try:
        value = float(dt_line[0])
    except (TypeError, ValueError, IndexError):
        return None
    if math.isnan(value):
        return None
    return num2date(value)


def _get_dtkey(dt: datetime, timeframe: TimeFrame) -> datetime:
    if timeframe == TimeFrame.Years:
        return datetime(dt.year, 12, 31)
    if timeframe == TimeFrame.Months:
        return datetime(dt.year, dt.month, 1)
    if timeframe == TimeFrame.Weeks:
        base = dt.replace(hour=0, minute=0, second=0, microsecond=0)
        return base - timedelta(days=dt.weekday())
    return datetime(dt.year, dt.month, dt.day)
