"""Trend indicators: MACD, Aroon, Trix, DirectionalMovement (ADX/DI),
ParabolicSAR, Ichimoku.
"""

from __future__ import annotations

import math
from typing import Any

from bucktrader.dataseries import LineBuffer
from bucktrader.indicator import Indicator
from bucktrader.indicators.basicops import _get_input_line
from bucktrader.indicators.matype import (
    EMA,
    SMA,
    ExponentialMovingAverage,
    SmoothedMovingAverage,
    MovAv,
)

NaN = float("nan")


# ---------------------------------------------------------------------------
# MACD
# ---------------------------------------------------------------------------


class MACD(Indicator):
    """Moving Average Convergence/Divergence.

    Lines:
        macd   -- EMA(fast) - EMA(slow)
        signal -- EMA(macd, period_signal)

    Default params: period_me1=12, period_me2=26, period_signal=9.
    """

    lines = ("macd", "signal")
    params = (
        ("period_me1", 12),
        ("period_me2", 26),
        ("period_signal", 9),
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._ema_fast = ExponentialMovingAverage(
            self.data, period=self.p.period_me1
        )
        self._ema_slow = ExponentialMovingAverage(
            self.data, period=self.p.period_me2
        )
        self._macd_line = LineBuffer(name="macd_internal")
        self._ema_signal = _DeferredEMA(self.p.period_signal)
        # Min period: the slower EMA's period + signal period - 1
        self._minperiod = self.p.period_me2 + self.p.period_signal - 1

    def next(self) -> None:
        _step_indicator(self._ema_fast)
        _step_indicator(self._ema_slow)
        fast = self._ema_fast.lines.av[0]
        slow = self._ema_slow.lines.av[0]
        macd_val = fast - slow
        self.lines.macd[0] = macd_val

        # Feed MACD value into the signal EMA
        self._macd_line.forward()
        self._macd_line[0] = macd_val

        signal_val = self._ema_signal.step(macd_val)
        self.lines.signal[0] = signal_val


class _DeferredEMA:
    """Lightweight EMA that processes values one at a time."""

    def __init__(self, period: int) -> None:
        self._period = period
        self._alpha = 2.0 / (period + 1.0)
        self._count = 0
        self._sum = 0.0
        self._value = NaN

    def step(self, new_val: float) -> float:
        """Process one new value and return the current EMA."""
        self._count += 1
        if self._count <= self._period:
            self._sum += new_val
            if self._count == self._period:
                self._value = self._sum / self._period
        else:
            self._value = self._value + self._alpha * (new_val - self._value)
        return self._value


# ---------------------------------------------------------------------------
# MACDHisto
# ---------------------------------------------------------------------------


class MACDHisto(MACD):
    """MACD with histogram line: histo = macd - signal."""

    lines = ("histo",)

    def next(self) -> None:
        super().next()
        self.lines.histo[0] = self.lines.macd[0] - self.lines.signal[0]


# ---------------------------------------------------------------------------
# Aroon
# ---------------------------------------------------------------------------


class Aroon(Indicator):
    """Aroon Up/Down indicator.

    Measures how many bars since the highest high and lowest low
    within a lookback period.

    Lines:
        aroonup   -- 100 * (period - bars_since_high) / period
        aroondown -- 100 * (period - bars_since_low) / period
    """

    lines = ("aroonup", "aroondown")
    params = (("period", 14),)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # Need period + 1 bars
        self.addminperiod(self.p.period + 1)

    def next(self) -> None:
        period = self.p.period

        # Get high and low lines
        high_line = _get_line(self.data, "high")
        low_line = _get_line(self.data, "low")

        if high_line is None or low_line is None:
            # Fallback: use close as both high and low
            close_line = _get_input_line(self.data)
            high_line = close_line
            low_line = close_line

        # Find bars since highest high and lowest low
        bars_since_high = 0
        bars_since_low = 0
        highest = high_line[0]
        lowest = low_line[0]

        for i in range(1, period + 1):
            h = high_line[-i]
            l = low_line[-i]
            if h >= highest:
                highest = h
                bars_since_high = i
            if l <= lowest:
                lowest = l
                bars_since_low = i

        self.lines.aroonup[0] = 100.0 * (period - bars_since_high) / period
        self.lines.aroondown[0] = 100.0 * (period - bars_since_low) / period


# ---------------------------------------------------------------------------
# AroonOscillator
# ---------------------------------------------------------------------------


class AroonOscillator(Indicator):
    """Aroon Oscillator: AroonUp - AroonDown."""

    lines = ("aroonosc",)
    params = (("period", 14),)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._aroon = Aroon(self.data, period=self.p.period)
        self._minperiod = self._aroon._minperiod

    def next(self) -> None:
        _step_indicator(self._aroon)
        self.lines.aroonosc[0] = (
            self._aroon.lines.aroonup[0] - self._aroon.lines.aroondown[0]
        )


# ---------------------------------------------------------------------------
# Trix
# ---------------------------------------------------------------------------


class Trix(Indicator):
    """Triple EMA rate of change.

    Applies EMA three times, then computes the 1-bar percentage change.

    Line: trix = 100 * (EMA3[0] - EMA3[-1]) / EMA3[-1]
    """

    lines = ("trix",)
    params = (("period", 15),)

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
        self._minperiod = self._ema3._minperiod + 1

    def next(self) -> None:
        _step_indicator(self._ema1)
        _step_indicator(self._ema2)
        _step_indicator(self._ema3)
        cur = self._ema3.lines.av[0]
        prev = self._ema3.lines.av[-1]
        if prev != 0:
            self.lines.trix[0] = 100.0 * (cur - prev) / prev
        else:
            self.lines.trix[0] = 0.0


# ---------------------------------------------------------------------------
# DirectionalMovement (ADX, +DI, -DI)
# ---------------------------------------------------------------------------


class DirectionalMovement(Indicator):
    """Directional Movement indicator with ADX, +DI, and -DI.

    Lines:
        plusDI  -- +DI (positive directional indicator)
        minusDI -- -DI (negative directional indicator)
        adx     -- ADX (average directional index)

    Uses Wilder's smoothing (SMMA).
    """

    lines = ("plusDI", "minusDI", "adx")
    params = (("period", 14),)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # Need 2 bars for directional movement, then period for smoothing
        self._minperiod = self.p.period + 1

        # Internal state for smoothed values
        self._tr_sum = 0.0
        self._plus_dm_sum = 0.0
        self._minus_dm_sum = 0.0
        self._adx_sum = 0.0
        self._bar_count = 0
        self._adx_count = 0
        self._initialized = False
        self._adx_initialized = False

    def next(self) -> None:
        period = self.p.period

        high_line = _get_line(self.data, "high")
        low_line = _get_line(self.data, "low")
        close_line = _get_input_line(self.data)

        if high_line is None or low_line is None:
            high_line = close_line
            low_line = close_line

        h = high_line[0]
        l = low_line[0]
        prev_h = high_line[-1]
        prev_l = low_line[-1]
        prev_c = close_line[-1]

        # True Range
        tr = max(h - l, abs(h - prev_c), abs(l - prev_c))

        # Directional Movement
        up_move = h - prev_h
        down_move = prev_l - l

        plus_dm = up_move if (up_move > down_move and up_move > 0) else 0.0
        minus_dm = down_move if (down_move > up_move and down_move > 0) else 0.0

        self._bar_count += 1

        if not self._initialized:
            self._tr_sum += tr
            self._plus_dm_sum += plus_dm
            self._minus_dm_sum += minus_dm

            if self._bar_count >= period:
                self._initialized = True
                # First smoothed values are simple sums
                smoothed_tr = self._tr_sum
                smoothed_plus = self._plus_dm_sum
                smoothed_minus = self._minus_dm_sum
                self._tr_sum = smoothed_tr
                self._plus_dm_sum = smoothed_plus
                self._minus_dm_sum = smoothed_minus

                if smoothed_tr != 0:
                    pdi = 100.0 * smoothed_plus / smoothed_tr
                    mdi = 100.0 * smoothed_minus / smoothed_tr
                else:
                    pdi = 0.0
                    mdi = 0.0

                self.lines.plusDI[0] = pdi
                self.lines.minusDI[0] = mdi

                # Start ADX accumulation
                di_sum = pdi + mdi
                if di_sum != 0:
                    dx = 100.0 * abs(pdi - mdi) / di_sum
                else:
                    dx = 0.0
                self._adx_sum += dx
                self._adx_count += 1

                if self._adx_count >= period:
                    self._adx_initialized = True
                    self._adx_val = self._adx_sum / period
                    self.lines.adx[0] = self._adx_val
                else:
                    self.lines.adx[0] = dx
        else:
            # Wilder's smoothing
            self._tr_sum = self._tr_sum - self._tr_sum / period + tr
            self._plus_dm_sum = (
                self._plus_dm_sum - self._plus_dm_sum / period + plus_dm
            )
            self._minus_dm_sum = (
                self._minus_dm_sum - self._minus_dm_sum / period + minus_dm
            )

            if self._tr_sum != 0:
                pdi = 100.0 * self._plus_dm_sum / self._tr_sum
                mdi = 100.0 * self._minus_dm_sum / self._tr_sum
            else:
                pdi = 0.0
                mdi = 0.0

            self.lines.plusDI[0] = pdi
            self.lines.minusDI[0] = mdi

            di_sum = pdi + mdi
            if di_sum != 0:
                dx = 100.0 * abs(pdi - mdi) / di_sum
            else:
                dx = 0.0

            self._adx_count += 1
            if not self._adx_initialized:
                self._adx_sum += dx
                if self._adx_count >= period:
                    self._adx_initialized = True
                    self._adx_val = self._adx_sum / period
                    self.lines.adx[0] = self._adx_val
                else:
                    self.lines.adx[0] = dx
            else:
                # Smooth ADX
                self._adx_val = (
                    self._adx_val * (period - 1) + dx
                ) / period
                self.lines.adx[0] = self._adx_val


DirectionalMovementIndex = DirectionalMovement


# ---------------------------------------------------------------------------
# ParabolicSAR
# ---------------------------------------------------------------------------


class ParabolicSAR(Indicator):
    """Parabolic Stop and Reverse."""

    lines = ("psar",)
    params = (
        ("af", 0.02),
        ("afmax", 0.2),
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.addminperiod(2)
        self._initialized = False
        self._long = True
        self._ep = 0.0
        self._sar = 0.0
        self._af = self.p.af

    def next(self) -> None:
        high_line = _get_line(self.data, "high")
        low_line = _get_line(self.data, "low")
        close_line = _get_input_line(self.data)
        if high_line is None or low_line is None:
            high_line = close_line
            low_line = close_line

        high = high_line[0]
        low = low_line[0]

        if not self._initialized:
            prev = close_line[-1]
            if math.isnan(prev):
                prev = close_line[0]
            self._long = close_line[0] >= prev
            self._ep = high if self._long else low
            prev_low = low_line[-1]
            prev_high = high_line[-1]
            if math.isnan(prev_low):
                prev_low = low
            if math.isnan(prev_high):
                prev_high = high
            self._sar = prev_low if self._long else prev_high
            self._initialized = True
            self.lines.psar[0] = self._sar
            return

        # Core SAR step
        self._sar = self._sar + self._af * (self._ep - self._sar)

        if self._long:
            if low < self._sar:
                # Reverse to short
                self._long = False
                self._sar = self._ep
                self._ep = low
                self._af = self.p.af
            else:
                if high > self._ep:
                    self._ep = high
                    self._af = min(self._af + self.p.af, self.p.afmax)
        else:
            if high > self._sar:
                # Reverse to long
                self._long = True
                self._sar = self._ep
                self._ep = high
                self._af = self.p.af
            else:
                if low < self._ep:
                    self._ep = low
                    self._af = min(self._af + self.p.af, self.p.afmax)

        self.lines.psar[0] = self._sar


# ---------------------------------------------------------------------------
# Ichimoku
# ---------------------------------------------------------------------------


class Ichimoku(Indicator):
    """Ichimoku Kinko Hyo."""

    lines = ("tenkan", "kijun", "senkou_a", "senkou_b", "chikou")
    params = (
        ("tenkan", 9),
        ("kijun", 26),
        ("senkou", 52),
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.addminperiod(self.p.senkou)

    def next(self) -> None:
        high_line = _get_line(self.data, "high")
        low_line = _get_line(self.data, "low")
        close_line = _get_input_line(self.data)
        if high_line is None or low_line is None:
            high_line = close_line
            low_line = close_line

        tenkan = _midpoint(high_line, low_line, self.p.tenkan)
        kijun = _midpoint(high_line, low_line, self.p.kijun)
        senkou_b = _midpoint(high_line, low_line, self.p.senkou)

        self.lines.tenkan[0] = tenkan
        self.lines.kijun[0] = kijun
        self.lines.senkou_a[0] = (tenkan + kijun) / 2.0
        self.lines.senkou_b[0] = senkou_b
        self.lines.chikou[0] = close_line[0]


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


def _midpoint(high_line: LineBuffer, low_line: LineBuffer, period: int) -> float:
    highest = high_line[0]
    lowest = low_line[0]
    for i in range(1, period):
        h = high_line[-i]
        l = low_line[-i]
        if h > highest:
            highest = h
        if l < lowest:
            lowest = l
    return (highest + lowest) / 2.0
