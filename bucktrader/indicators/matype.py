"""Moving Average indicators.

Provides SMA, EMA, WMA, SMMA, KAMA, DEMA, TEMA, ZLEMA, HMA, and a MovAv
namespace for convenient access.
"""

from __future__ import annotations

import math
from typing import Any

from bucktrader.dataseries import LineBuffer
from bucktrader.indicator import Indicator
from bucktrader.indicators.basicops import PeriodN, _get_input_line

NaN = float("nan")


# ---------------------------------------------------------------------------
# MovingAverageBase -- shared base with period param
# ---------------------------------------------------------------------------


class MovingAverageBase(PeriodN):
    """Base class for all moving averages.

    Subclasses inherit the ``period`` parameter and must define one output
    line (the moving average value).
    """

    lines = ("av",)


# ---------------------------------------------------------------------------
# SimpleMovingAverage (SMA)
# ---------------------------------------------------------------------------


class SimpleMovingAverage(MovingAverageBase):
    """Simple Moving Average: arithmetic mean over a rolling window."""

    alias = ("SMA",)

    def next(self) -> None:
        src = _get_input_line(self.data)
        values = src.get(ago=0, size=self.p.period)
        clean = [v for v in values if not math.isnan(v)]
        if not clean:
            self.lines.av[0] = src[0]
        else:
            self.lines.av[0] = float(sum(clean)) / len(clean)

    def once(self, start: int, end: int) -> None:
        src = _get_input_line(self.data)
        dst = self.lines.av
        period = self.p.period
        for i in range(start, end):
            s = max(0, i - period + 1)
            window = src._array[s: i + 1]
            dst._array[i] = float(sum(window)) / period


SMA = SimpleMovingAverage


# ---------------------------------------------------------------------------
# ExponentialMovingAverage (EMA)
# ---------------------------------------------------------------------------


class ExponentialMovingAverage(MovingAverageBase):
    """Exponential Moving Average with alpha = 2 / (period + 1)."""

    alias = ("EMA",)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._alpha: float = 2.0 / (self.p.period + 1.0)
        self._ema_initialized: bool = False

    def next(self) -> None:
        src = _get_input_line(self.data)
        dst = self.lines.av

        if not self._ema_initialized:
            # Seed with SMA of first 'period' values
            values = src.get(ago=0, size=self.p.period)
            clean = [v for v in values if not math.isnan(v)]
            if not clean:
                dst[0] = src[0]
            else:
                dst[0] = float(sum(clean)) / len(clean)
            self._ema_initialized = True
        else:
            prev = dst[-1]
            cur = src[0]
            dst[0] = prev + self._alpha * (cur - prev)

    def once(self, start: int, end: int) -> None:
        src = _get_input_line(self.data)
        dst = self.lines.av
        period = self.p.period
        alpha = self._alpha

        if start >= end:
            return

        # Seed the first valid bar with SMA
        first = start
        s = max(0, first - period + 1)
        window = src._array[s: first + 1]
        dst._array[first] = float(sum(window)) / period

        # Compute remaining bars using EMA formula
        for i in range(first + 1, end):
            prev = dst._array[i - 1]
            cur = src._array[i]
            dst._array[i] = prev + alpha * (cur - prev)


EMA = ExponentialMovingAverage


# ---------------------------------------------------------------------------
# WeightedMovingAverage (WMA)
# ---------------------------------------------------------------------------


class WeightedMovingAverage(MovingAverageBase):
    """Weighted Moving Average: linearly weighted by position.

    Weight of bar i (most recent) = period - i + 1, where the most recent
    bar gets the highest weight.
    """

    alias = ("WMA",)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        p = self.p.period
        # Weights: [1, 2, 3, ..., period]  (oldest to newest)
        self._weights = list(range(1, p + 1))
        self._weight_sum = sum(self._weights)

    def next(self) -> None:
        src = _get_input_line(self.data)
        values = src.get(ago=0, size=self.p.period)
        weighted = 0.0
        wsum = 0.0
        for v, w in zip(values, self._weights):
            if math.isnan(v):
                continue
            weighted += v * w
            wsum += w
        self.lines.av[0] = src[0] if wsum == 0 else weighted / wsum

    def once(self, start: int, end: int) -> None:
        src = _get_input_line(self.data)
        dst = self.lines.av
        period = self.p.period
        weights = self._weights
        wsum = self._weight_sum
        for i in range(start, end):
            s = max(0, i - period + 1)
            window = src._array[s: i + 1]
            # If window is smaller than period, use tail of weights
            w = weights[period - len(window):]
            weighted = sum(v * wt for v, wt in zip(window, w))
            dst._array[i] = weighted / wsum


WMA = WeightedMovingAverage


# ---------------------------------------------------------------------------
# SmoothedMovingAverage (SMMA) -- Wilder's smoothing
# ---------------------------------------------------------------------------


class SmoothedMovingAverage(MovingAverageBase):
    """Smoothed Moving Average (Wilder's smoothing).

    alpha = 1 / period.  Equivalent to an EMA with period = 2*period - 1.
    """

    alias = ("SMMA",)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._alpha: float = 1.0 / self.p.period
        self._initialized: bool = False

    def next(self) -> None:
        src = _get_input_line(self.data)
        dst = self.lines.av

        if not self._initialized:
            # Seed with SMA
            values = src.get(ago=0, size=self.p.period)
            clean = [v for v in values if not math.isnan(v)]
            if not clean:
                dst[0] = src[0]
            else:
                dst[0] = float(sum(clean)) / len(clean)
            self._initialized = True
        else:
            prev = dst[-1]
            cur = src[0]
            dst[0] = prev + self._alpha * (cur - prev)

    def once(self, start: int, end: int) -> None:
        src = _get_input_line(self.data)
        dst = self.lines.av
        period = self.p.period
        alpha = self._alpha

        if start >= end:
            return

        first = start
        s = max(0, first - period + 1)
        window = src._array[s: first + 1]
        dst._array[first] = float(sum(window)) / period

        for i in range(first + 1, end):
            prev = dst._array[i - 1]
            cur = src._array[i]
            dst._array[i] = prev + alpha * (cur - prev)


SMMA = SmoothedMovingAverage


# ---------------------------------------------------------------------------
# AdaptiveMovingAverage (KAMA) -- Kaufman's
# ---------------------------------------------------------------------------


class AdaptiveMovingAverage(MovingAverageBase):
    """Kaufman Adaptive Moving Average (KAMA).

    Adapts smoothing factor based on the efficiency ratio:
        ER = |direction| / volatility
        sc = (ER * (fast_sc - slow_sc) + slow_sc) ** 2

    Default fast period = 2, slow period = 30.
    """

    alias = ("KAMA",)
    params = (
        ("fast", 2),
        ("slow", 30),
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._fast_sc: float = 2.0 / (self.p.fast + 1.0)
        self._slow_sc: float = 2.0 / (self.p.slow + 1.0)
        self._initialized: bool = False

    def next(self) -> None:
        src = _get_input_line(self.data)
        dst = self.lines.av
        period = self.p.period

        if not self._initialized:
            dst[0] = src[0]
            self._initialized = True
            return

        # Efficiency ratio
        direction = abs(src[0] - src[-period])
        volatility = 0.0
        for i in range(period):
            volatility += abs(src[-i] - src[-i - 1])

        if volatility == 0:
            er = 0.0
        else:
            er = direction / volatility

        sc = (er * (self._fast_sc - self._slow_sc) + self._slow_sc) ** 2
        prev = dst[-1]
        dst[0] = prev + sc * (src[0] - prev)


KAMA = AdaptiveMovingAverage


# ---------------------------------------------------------------------------
# DoubleExponentialMovingAverage (DEMA)
# ---------------------------------------------------------------------------


class DoubleExponentialMovingAverage(MovingAverageBase):
    """Double Exponential Moving Average: 2*EMA - EMA(EMA).

    Reduces lag compared to a standard EMA.
    """

    alias = ("DEMA",)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._ema1 = ExponentialMovingAverage(
            self.data, period=self.p.period
        )
        self._ema2 = ExponentialMovingAverage(
            self._ema1, period=self.p.period
        )
        # DEMA needs period bars for EMA1, then period-1 more for EMA2
        self._minperiod = self._ema2._minperiod

    def next(self) -> None:
        _step_indicator(self._ema1)
        _step_indicator(self._ema2)
        e1 = self._ema1.lines.av[0]
        e2 = self._ema2.lines.av[0]
        self.lines.av[0] = 2.0 * e1 - e2


DEMA = DoubleExponentialMovingAverage


# ---------------------------------------------------------------------------
# TripleExponentialMovingAverage (TEMA)
# ---------------------------------------------------------------------------


class TripleExponentialMovingAverage(MovingAverageBase):
    """Triple Exponential Moving Average: 3*EMA - 3*EMA(EMA) + EMA(EMA(EMA)).

    Further reduces lag compared to DEMA.
    """

    alias = ("TEMA",)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._ema1 = ExponentialMovingAverage(
            self.data, period=self.p.period
        )
        self._ema2 = ExponentialMovingAverage(
            self._ema1, period=self.p.period
        )
        self._ema3 = ExponentialMovingAverage(
            self._ema2, period=self.p.period
        )
        self._minperiod = self._ema3._minperiod

    def next(self) -> None:
        _step_indicator(self._ema1)
        _step_indicator(self._ema2)
        _step_indicator(self._ema3)
        e1 = self._ema1.lines.av[0]
        e2 = self._ema2.lines.av[0]
        e3 = self._ema3.lines.av[0]
        self.lines.av[0] = 3.0 * e1 - 3.0 * e2 + e3


TEMA = TripleExponentialMovingAverage


# ---------------------------------------------------------------------------
# ZeroLagExponentialMovingAverage (ZLEMA)
# ---------------------------------------------------------------------------


class ZeroLagExponentialMovingAverage(MovingAverageBase):
    """Zero-Lag EMA: applies EMA to a lag-compensated series.

    Compensated value = 2 * price - price(lag), where lag = (period-1)/2.
    """

    alias = ("ZLEMA",)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._lag: int = (self.p.period - 1) // 2
        self._alpha: float = 2.0 / (self.p.period + 1.0)
        self._initialized: bool = False
        # Need extra bars for the lag lookback
        if self._lag > 0:
            self.addminperiod(self._lag)

    def next(self) -> None:
        src = _get_input_line(self.data)
        dst = self.lines.av

        compensated = 2.0 * src[0] - src[-self._lag]

        if not self._initialized:
            dst[0] = compensated
            self._initialized = True
        else:
            prev = dst[-1]
            dst[0] = prev + self._alpha * (compensated - prev)


ZLEMA = ZeroLagExponentialMovingAverage


# ---------------------------------------------------------------------------
# HullMovingAverage (HMA)
# ---------------------------------------------------------------------------


class HullMovingAverage(MovingAverageBase):
    """Hull Moving Average: WMA(2*WMA(n/2) - WMA(n), sqrt(n)).

    Provides much less lag than SMA/EMA with similar smoothing.
    """

    alias = ("HMA",)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        period = self.p.period
        half_period = max(1, period // 2)
        sqrt_period = max(1, int(math.sqrt(period)))

        self._wma_half = WeightedMovingAverage(
            self.data, period=half_period
        )
        self._wma_full = WeightedMovingAverage(
            self.data, period=period
        )
        # The diff line (2*WMA_half - WMA_full) is computed bar-by-bar,
        # then WMA of that diff.
        self._diff = LineBuffer(name="hma_diff")
        self._wma_sqrt = _InternalWMA(sqrt_period)

        # HMA's min period: period bars for WMA_full, then sqrt_period-1
        # more for the final WMA.
        self._minperiod = period + sqrt_period - 1

    def next(self) -> None:
        _step_indicator(self._wma_half)
        _step_indicator(self._wma_full)
        half_val = self._wma_half.lines.av[0]
        full_val = self._wma_full.lines.av[0]
        diff = 2.0 * half_val - full_val

        self._diff.forward()
        self._diff[0] = diff

        sqrt_period = self._wma_sqrt._period
        if len(self._diff) >= sqrt_period:
            values = self._diff.get(ago=0, size=sqrt_period)
            self.lines.av[0] = self._wma_sqrt.compute(values)
        else:
            self.lines.av[0] = diff


HMA = HullMovingAverage


class _InternalWMA:
    """Lightweight WMA computation helper (no line management)."""

    def __init__(self, period: int) -> None:
        self._period = period
        self._weights = list(range(1, period + 1))
        self._weight_sum = sum(self._weights)

    def compute(self, values) -> float:
        """Compute WMA of the given values array."""
        n = len(values)
        if n < self._period:
            weights = self._weights[self._period - n:]
        else:
            weights = self._weights
        weighted = sum(v * w for v, w in zip(values, weights))
        return weighted / self._weight_sum


# ---------------------------------------------------------------------------
# MovAv namespace
# ---------------------------------------------------------------------------


class MovAv:
    """Namespace providing convenient access to all moving average types."""

    Simple = SimpleMovingAverage
    SMA = SimpleMovingAverage
    Exponential = ExponentialMovingAverage
    EMA = ExponentialMovingAverage
    Weighted = WeightedMovingAverage
    WMA = WeightedMovingAverage
    Smoothed = SmoothedMovingAverage
    SMMA = SmoothedMovingAverage
    Adaptive = AdaptiveMovingAverage
    KAMA = AdaptiveMovingAverage
    DEMA = DoubleExponentialMovingAverage
    TEMA = TripleExponentialMovingAverage
    ZLEMA = ZeroLagExponentialMovingAverage
    Hull = HullMovingAverage
    HMA = HullMovingAverage


def _step_indicator(ind: Any) -> None:
    """Advance one bar on a child indicator."""
    if hasattr(ind, "lines") and hasattr(ind.lines, "forward"):
        ind.lines.forward()
    ind.next()
