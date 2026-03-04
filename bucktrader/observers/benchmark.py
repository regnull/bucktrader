"""Benchmark return observer."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from bucktrader.dataseries import TimeFrame, num2date
from bucktrader.observer import Observer


NaN = float("nan")


class Benchmark(Observer):
    """Observer that tracks benchmark period returns."""

    _line_names = ("bench",)

    def __init__(
        self,
        strategy: Any = None,
        data: Any = None,
        timeframe: TimeFrame = TimeFrame.Days,
        compression: int = 1,
    ) -> None:
        super().__init__(strategy)
        self._bench_data = data
        self.timeframe = timeframe
        self.compression = compression
        self._period_key: datetime | None = None
        self._period_start_price: float | None = None

    def next(self) -> None:
        data = self._bench_data or self.data
        if data is None:
            self.lines.bench[0] = NaN
            return

        dt = _get_dt(data)
        price = _get_price(data)
        if dt is None or price is None:
            self.lines.bench[0] = NaN
            return

        key = _get_dtkey(dt, self.timeframe)

        if self._period_key is None:
            self._period_key = key
            self._period_start_price = price
            self.lines.bench[0] = NaN
            return

        if key != self._period_key:
            if self._period_start_price and self._period_start_price != 0:
                self.lines.bench[0] = (price / self._period_start_price) - 1.0
            else:
                self.lines.bench[0] = NaN
            self._period_key = key
            self._period_start_price = price
            return

        self.lines.bench[0] = NaN


def _get_dt(data: Any) -> datetime | None:
    dt_line = getattr(data, "datetime", None)
    if dt_line is None or not callable(getattr(dt_line, "__getitem__", None)):
        return None
    try:
        val = float(dt_line[0])
    except (TypeError, ValueError, IndexError):
        return None
    if math.isnan(val):
        return None
    return num2date(val)


def _get_price(data: Any) -> float | None:
    close = getattr(data, "close", None)
    if close is None:
        return None
    if callable(getattr(close, "__getitem__", None)):
        try:
            return float(close[0])
        except (TypeError, ValueError, IndexError):
            return None
    if isinstance(close, (int, float)):
        return float(close)
    return None


def _get_dtkey(dt: datetime, timeframe: TimeFrame) -> datetime:
    if timeframe == TimeFrame.Years:
        return datetime(dt.year, 12, 31)
    if timeframe == TimeFrame.Months:
        return datetime(dt.year, dt.month, 1)
    return datetime(dt.year, dt.month, dt.day)
