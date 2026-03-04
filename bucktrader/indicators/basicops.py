"""Basic operation indicators -- foundation for all other indicators.

These provide period-based aggregation (Highest, Lowest, SumN, Average),
cumulative operations (Accum), boolean aggregation (AnyN, AllN), and
crossover detection (CrossOver, CrossUp, CrossDown).
"""

from __future__ import annotations

import math
from typing import Any, Callable

from bucktrader.dataseries import LineBuffer
from bucktrader.indicator import Indicator

NaN = float("nan")


# ---------------------------------------------------------------------------
# PeriodN -- Base for all period-based indicators
# ---------------------------------------------------------------------------


class PeriodN(Indicator):
    """Base class for indicators that operate over a rolling window.

    Adds ``self.p.period`` to the minimum period during construction.
    Subclasses override ``next()`` (and optionally ``once()``) to compute
    their output.
    """

    params = (("period", 1),)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.addminperiod(self.p.period)


# ---------------------------------------------------------------------------
# OperationN -- Apply a callable over a period window
# ---------------------------------------------------------------------------


class OperationN(PeriodN):
    """Apply a function over a rolling window of the input data.

    The ``func`` parameter receives a numpy array of ``period`` values
    and should return a scalar.
    """

    params = (("func", None),)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if self.p.func is None:
            raise ValueError("OperationN requires a 'func' parameter")

    def next(self) -> None:
        src = _get_input_line(self.data)
        values = src.get(ago=0, size=self.p.period)
        self.lines[0][0] = self.p.func(values)

    def once(self, start: int, end: int) -> None:
        src = _get_input_line(self.data)
        dst = self.lines[0]
        period = self.p.period
        func = self.p.func
        for i in range(start, end):
            dst._array[i] = func(src._array[max(0, i - period + 1): i + 1])


# ---------------------------------------------------------------------------
# Highest / Lowest / SumN / Average
# ---------------------------------------------------------------------------


class Highest(PeriodN):
    """Maximum value over a rolling window."""

    lines = ("highest",)

    def next(self) -> None:
        src = _get_input_line(self.data)
        values = src.get(ago=0, size=self.p.period)
        self.lines.highest[0] = float(max(values))

    def once(self, start: int, end: int) -> None:
        src = _get_input_line(self.data)
        dst = self.lines.highest
        period = self.p.period
        for i in range(start, end):
            s = max(0, i - period + 1)
            dst._array[i] = float(max(src._array[s: i + 1]))


class Lowest(PeriodN):
    """Minimum value over a rolling window."""

    lines = ("lowest",)

    def next(self) -> None:
        src = _get_input_line(self.data)
        values = src.get(ago=0, size=self.p.period)
        self.lines.lowest[0] = float(min(values))

    def once(self, start: int, end: int) -> None:
        src = _get_input_line(self.data)
        dst = self.lines.lowest
        period = self.p.period
        for i in range(start, end):
            s = max(0, i - period + 1)
            dst._array[i] = float(min(src._array[s: i + 1]))


class SumN(PeriodN):
    """Sum over a rolling window."""

    lines = ("sum",)

    def next(self) -> None:
        src = _get_input_line(self.data)
        values = src.get(ago=0, size=self.p.period)
        self.lines.sum[0] = float(sum(values))

    def once(self, start: int, end: int) -> None:
        src = _get_input_line(self.data)
        dst = self.lines.sum
        period = self.p.period
        for i in range(start, end):
            s = max(0, i - period + 1)
            dst._array[i] = float(sum(src._array[s: i + 1]))


class Average(PeriodN):
    """Arithmetic mean over a rolling window."""

    lines = ("av",)

    def next(self) -> None:
        src = _get_input_line(self.data)
        values = src.get(ago=0, size=self.p.period)
        self.lines.av[0] = float(sum(values)) / self.p.period

    def once(self, start: int, end: int) -> None:
        src = _get_input_line(self.data)
        dst = self.lines.av
        period = self.p.period
        for i in range(start, end):
            s = max(0, i - period + 1)
            dst._array[i] = float(sum(src._array[s: i + 1])) / period


# ---------------------------------------------------------------------------
# Accum -- Cumulative sum
# ---------------------------------------------------------------------------


class Accum(Indicator):
    """Cumulative (running) sum of the input data."""

    lines = ("accum",)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._cumsum: float = 0.0

    def next(self) -> None:
        src = _get_input_line(self.data)
        self._cumsum += src[0]
        self.lines.accum[0] = self._cumsum


# ---------------------------------------------------------------------------
# AnyN / AllN -- Boolean aggregation over a period
# ---------------------------------------------------------------------------


class AnyN(PeriodN):
    """Returns 1.0 if any value in the period is non-zero, else 0.0."""

    lines = ("anyn",)

    def next(self) -> None:
        src = _get_input_line(self.data)
        values = src.get(ago=0, size=self.p.period)
        self.lines.anyn[0] = 1.0 if any(v != 0 for v in values) else 0.0


class AllN(PeriodN):
    """Returns 1.0 if all values in the period are non-zero, else 0.0."""

    lines = ("alln",)

    def next(self) -> None:
        src = _get_input_line(self.data)
        values = src.get(ago=0, size=self.p.period)
        self.lines.alln[0] = 1.0 if all(v != 0 for v in values) else 0.0


# ---------------------------------------------------------------------------
# CrossOver / CrossUp / CrossDown
# ---------------------------------------------------------------------------


class CrossOver(Indicator):
    """Detect crossovers between two data lines.

    Expects two data inputs: data0 and data1.
    Output: +1.0 when data0 crosses above data1 (CrossUp),
            -1.0 when data0 crosses below data1 (CrossDown),
             0.0 otherwise.

    Requires at least 2 bars to detect a cross.
    """

    lines = ("crossover",)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # Need 2 bars to compare current vs previous
        self.addminperiod(2)

    def next(self) -> None:
        d0 = _get_input_line(self.datas[0])
        d1 = _get_input_line(self.datas[1])

        # Current and previous values
        cur0, cur1 = d0[0], d1[0]
        prev0, prev1 = d0[-1], d1[-1]

        if prev0 <= prev1 and cur0 > cur1:
            self.lines.crossover[0] = 1.0
        elif prev0 >= prev1 and cur0 < cur1:
            self.lines.crossover[0] = -1.0
        else:
            self.lines.crossover[0] = 0.0


class CrossUp(Indicator):
    """Detect when data0 crosses above data1.

    Output: 1.0 on upward cross, 0.0 otherwise.
    """

    lines = ("crossup",)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.addminperiod(2)

    def next(self) -> None:
        d0 = _get_input_line(self.datas[0])
        d1 = _get_input_line(self.datas[1])

        cur0, cur1 = d0[0], d1[0]
        prev0, prev1 = d0[-1], d1[-1]

        if prev0 <= prev1 and cur0 > cur1:
            self.lines.crossup[0] = 1.0
        else:
            self.lines.crossup[0] = 0.0


class CrossDown(Indicator):
    """Detect when data0 crosses below data1.

    Output: 1.0 on downward cross, 0.0 otherwise.
    """

    lines = ("crossdown",)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.addminperiod(2)

    def next(self) -> None:
        d0 = _get_input_line(self.datas[0])
        d1 = _get_input_line(self.datas[1])

        cur0, cur1 = d0[0], d1[0]
        prev0, prev1 = d0[-1], d1[-1]

        if prev0 >= prev1 and cur0 < cur1:
            self.lines.crossdown[0] = 1.0
        else:
            self.lines.crossdown[0] = 0.0


# ---------------------------------------------------------------------------
# Helper: extract the input LineBuffer from a data source
# ---------------------------------------------------------------------------


def _get_input_line(data: Any) -> LineBuffer:
    """Return the primary input LineBuffer from various data types.

    Handles:
      - LineBuffer directly
      - DataSeries (returns .close)
      - Indicator (returns first output line)
      - Object with .close attribute
    """
    if isinstance(data, LineBuffer):
        return data
    if hasattr(data, "close") and isinstance(data.close, LineBuffer):
        return data.close
    if isinstance(data, Indicator):
        return data.lines[0]
    if hasattr(data, "lines"):
        lines = data.lines
        if hasattr(lines, "__getitem__"):
            return lines[0]
    raise TypeError(f"Cannot extract input line from {type(data)}: {data!r}")
