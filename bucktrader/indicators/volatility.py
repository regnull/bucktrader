"""Volatility indicators: TrueRange, ATR, BollingerBands, StdDev, MeanDeviation."""

from __future__ import annotations

import math
from typing import Any

from bucktrader.dataseries import LineBuffer
from bucktrader.indicator import Indicator
from bucktrader.indicators.basicops import _get_input_line
from bucktrader.indicators.matype import SMA, SimpleMovingAverage, MovAv

NaN = float("nan")


# ---------------------------------------------------------------------------
# TrueHigh / TrueLow
# ---------------------------------------------------------------------------


class TrueHigh(Indicator):
    """Gap-adjusted high: max(high, prev_close)."""

    lines = ("truehigh",)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.addminperiod(2)

    def next(self) -> None:
        high_line = _get_line(self.data, "high")
        close_line = _get_input_line(self.data)

        if high_line is None:
            high_line = close_line

        self.lines.truehigh[0] = max(high_line[0], close_line[-1])


class TrueLow(Indicator):
    """Gap-adjusted low: min(low, prev_close)."""

    lines = ("truelow",)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.addminperiod(2)

    def next(self) -> None:
        low_line = _get_line(self.data, "low")
        close_line = _get_input_line(self.data)

        if low_line is None:
            low_line = close_line

        self.lines.truelow[0] = min(low_line[0], close_line[-1])


# ---------------------------------------------------------------------------
# TrueRange
# ---------------------------------------------------------------------------


class TrueRange(Indicator):
    """True Range: max(H-L, |H-prevC|, |L-prevC|).

    Accounts for gap openings.
    """

    lines = ("tr",)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.addminperiod(2)

    def next(self) -> None:
        high_line = _get_line(self.data, "high")
        low_line = _get_line(self.data, "low")
        close_line = _get_input_line(self.data)

        if high_line is None:
            high_line = close_line
        if low_line is None:
            low_line = close_line

        h = high_line[0]
        l = low_line[0]
        prev_c = close_line[-1]

        self.lines.tr[0] = max(h - l, abs(h - prev_c), abs(l - prev_c))


# ---------------------------------------------------------------------------
# AverageTrueRange (ATR)
# ---------------------------------------------------------------------------


class AverageTrueRange(Indicator):
    """Average True Range: smoothed average of TrueRange.

    Uses Wilder's smoothing (SMMA / RMA).

    Lines: atr
    Default period: 14
    """

    lines = ("atr",)
    params = (("period", 14),)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._tr = TrueRange(self.data)
        # period for TR (2 bars min) + period for smoothing
        self._minperiod = self.p.period + 1

        self._initialized = False
        self._tr_values: list[float] = []
        self._atr_val = 0.0

    def next(self) -> None:
        _step_indicator(self._tr)
        period = self.p.period
        tr_val = self._tr.lines.tr[0]

        if not self._initialized:
            self._tr_values.append(tr_val)
            if len(self._tr_values) >= period:
                self._initialized = True
                self._atr_val = sum(self._tr_values) / period
                self.lines.atr[0] = self._atr_val
        else:
            # Wilder's smoothing
            self._atr_val = (
                self._atr_val * (period - 1) + tr_val
            ) / period
            self.lines.atr[0] = self._atr_val


ATR = AverageTrueRange


# ---------------------------------------------------------------------------
# StandardDeviation (StdDev)
# ---------------------------------------------------------------------------


class StandardDeviation(Indicator):
    """Standard deviation over a rolling window.

    Uses population standard deviation (ddof=0).
    """

    lines = ("stddev",)
    params = (("period", 20),)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.addminperiod(self.p.period)

    def next(self) -> None:
        src = _get_input_line(self.data)
        period = self.p.period
        values = src.get(ago=0, size=period)
        mean = float(sum(values)) / period
        variance = sum((v - mean) ** 2 for v in values) / period
        self.lines.stddev[0] = math.sqrt(variance)


StdDev = StandardDeviation


# ---------------------------------------------------------------------------
# MeanDeviation
# ---------------------------------------------------------------------------


class MeanDeviation(Indicator):
    """Mean absolute deviation over a rolling window."""

    lines = ("meandev",)
    params = (("period", 20),)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.addminperiod(self.p.period)

    def next(self) -> None:
        src = _get_input_line(self.data)
        period = self.p.period
        values = src.get(ago=0, size=period)
        mean = float(sum(values)) / period
        self.lines.meandev[0] = sum(abs(v - mean) for v in values) / period


# ---------------------------------------------------------------------------
# BollingerBands
# ---------------------------------------------------------------------------


class BollingerBands(Indicator):
    """Bollinger Bands: SMA +/- N standard deviations.

    Lines:
        mid -- SMA(close, period)
        top -- mid + devfactor * StdDev(close, period)
        bot -- mid - devfactor * StdDev(close, period)

    Params: period=20, devfactor=2.0, movav=SimpleMovingAverage
    """

    lines = ("mid", "top", "bot")
    params = (
        ("period", 20),
        ("devfactor", 2.0),
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        # Accept movav kwarg before super().__init__ consumes it
        movav = kwargs.pop("movav", SimpleMovingAverage)
        super().__init__(*args, **kwargs)
        self._movav = movav
        self.addminperiod(self.p.period)

        # Internal MA and StdDev
        self._ma = movav(self.data, period=self.p.period)
        self._stddev = StandardDeviation(self.data, period=self.p.period)

    def next(self) -> None:
        _step_indicator(self._ma)
        _step_indicator(self._stddev)
        mid = self._ma.lines.av[0]
        std = self._stddev.lines.stddev[0]
        dev = self.p.devfactor * std

        self.lines.mid[0] = mid
        self.lines.top[0] = mid + dev
        self.lines.bot[0] = mid - dev


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _get_line(data: Any, name: str) -> LineBuffer | None:
    """Try to get a named line from a data source."""
    line = getattr(data, name, None)
    if isinstance(line, LineBuffer):
        return line
    if hasattr(data, "_lines") and isinstance(data._lines, dict):
        return data._lines.get(name)
    return None


def _step_indicator(ind: Any) -> None:
    """Advance one bar on a child indicator."""
    if hasattr(ind, "lines") and hasattr(ind.lines, "forward"):
        ind.lines.forward()
    ind.next()
