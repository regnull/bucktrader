"""Other indicators: PivotPoint, HeikinAshi, ZigZag, Envelope."""

from __future__ import annotations

from typing import Any

from bucktrader.dataseries import LineBuffer
from bucktrader.indicator import Indicator
from bucktrader.indicators.basicops import _get_input_line
from bucktrader.indicators.matype import SimpleMovingAverage


class PivotPoint(Indicator):
    """Classic pivot points based on previous bar."""

    lines = ("p", "r1", "r2", "r3", "s1", "s2", "s3")

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.addminperiod(2)

    def next(self) -> None:
        high = _get_line(self.data, "high")
        low = _get_line(self.data, "low")
        close = _get_input_line(self.data)
        if high is None or low is None:
            h = l = c = close[-1]
        else:
            h = high[-1]
            l = low[-1]
            c = close[-1]

        p = (h + l + c) / 3.0
        self.lines.p[0] = p
        self.lines.r1[0] = 2 * p - l
        self.lines.s1[0] = 2 * p - h
        self.lines.r2[0] = p + (h - l)
        self.lines.s2[0] = p - (h - l)
        self.lines.r3[0] = h + 2 * (p - l)
        self.lines.s3[0] = l - 2 * (h - p)


class HeikinAshi(Indicator):
    """Heikin-Ashi transformed OHLC."""

    lines = ("ha_open", "ha_high", "ha_low", "ha_close")

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._initialized = False

    def next(self) -> None:
        high = _get_line(self.data, "high")
        low = _get_line(self.data, "low")
        close = _get_input_line(self.data)
        open_line = _get_line(self.data, "open")

        c = close[0]
        o = open_line[0] if open_line is not None else close[-1]
        h = high[0] if high is not None else c
        l = low[0] if low is not None else c

        ha_close = (o + h + l + c) / 4.0
        if not self._initialized:
            ha_open = (o + c) / 2.0
            self._initialized = True
        else:
            ha_open = (self.lines.ha_open[-1] + self.lines.ha_close[-1]) / 2.0

        self.lines.ha_open[0] = ha_open
        self.lines.ha_close[0] = ha_close
        self.lines.ha_high[0] = max(h, ha_open, ha_close)
        self.lines.ha_low[0] = min(l, ha_open, ha_close)


class ZigZag(Indicator):
    """Simple zigzag by percentage reversal threshold."""

    lines = ("zigzag",)
    params = (("retrace", 5.0),)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._pivot = None
        self._trend = 0

    def next(self) -> None:
        src = _get_input_line(self.data)
        price = src[0]
        if self._pivot is None:
            self._pivot = price
            self.lines.zigzag[0] = price
            return

        threshold = abs(self._pivot) * (self.p.retrace / 100.0)
        diff = price - self._pivot

        if self._trend >= 0 and diff >= 0:
            self._pivot = price
            self._trend = 1
            self.lines.zigzag[0] = price
        elif self._trend <= 0 and diff <= 0:
            self._pivot = price
            self._trend = -1
            self.lines.zigzag[0] = price
        elif abs(diff) >= threshold:
            self._pivot = price
            self._trend = 1 if diff > 0 else -1
            self.lines.zigzag[0] = price
        else:
            self.lines.zigzag[0] = self.lines.zigzag[-1]


class Envelope(Indicator):
    """MA envelope around a moving average."""

    lines = ("mid", "top", "bot")
    params = (
        ("period", 20),
        ("perc", 2.5),
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        movav = kwargs.pop("movav", SimpleMovingAverage)
        super().__init__(*args, **kwargs)
        self._ma = movav(self.data, period=self.p.period)
        self.addminperiod(self.p.period)

    def next(self) -> None:
        if hasattr(self._ma.lines, "forward"):
            self._ma.lines.forward()
        self._ma.next()

        mid = self._ma.lines.av[0]
        delta = mid * (self.p.perc / 100.0)
        self.lines.mid[0] = mid
        self.lines.top[0] = mid + delta
        self.lines.bot[0] = mid - delta


def _get_line(data: Any, name: str) -> LineBuffer | None:
    line = getattr(data, name, None)
    if isinstance(line, LineBuffer):
        return line
    if hasattr(data, "_lines") and isinstance(data._lines, dict):
        return data._lines.get(name)
    return None
