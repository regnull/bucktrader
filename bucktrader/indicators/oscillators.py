"""Oscillator indicators: RSI, Stochastic, WilliamsR, UltimateOscillator,
CCI, MomentumOscillator, RateOfChange, DPO, PPO.
"""

from __future__ import annotations

import math
from typing import Any

from bucktrader.dataseries import LineBuffer
from bucktrader.indicator import Indicator
from bucktrader.indicators.basicops import _get_input_line
from bucktrader.indicators.matype import (
    SMA,
    SmoothedMovingAverage,
    SimpleMovingAverage,
    MovAv,
)

NaN = float("nan")


# ---------------------------------------------------------------------------
# RSI -- Relative Strength Index
# ---------------------------------------------------------------------------


class RSI(Indicator):
    """Relative Strength Index.

    Computes up-day and down-day averages using Wilder's smoothing (SMMA),
    then: RSI = 100 - 100 / (1 + RS), where RS = avg_up / avg_down.

    Lines: rsi
    Default period: 14
    """

    lines = ("rsi",)
    params = (
        ("period", 14),
        ("upperband", 70.0),
        ("lowerband", 30.0),
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        period = self.p.period
        # Need 1 extra bar for the first difference, then period for smoothing
        self._minperiod = period + 1

        self._up_avg = 0.0
        self._down_avg = 0.0
        self._bar_count = 0
        self._ups: list[float] = []
        self._downs: list[float] = []
        self._initialized = False

    def next(self) -> None:
        src = _get_input_line(self.data)
        period = self.p.period

        prev = src[-1]
        if math.isnan(prev):
            prev = src[0]
        change = src[0] - prev
        up = max(change, 0.0)
        down = max(-change, 0.0)

        self._bar_count += 1

        if not self._initialized:
            self._ups.append(up)
            self._downs.append(down)

            if len(self._ups) >= period:
                self._initialized = True
                self._up_avg = sum(self._ups) / period
                self._down_avg = sum(self._downs) / period
                self._set_rsi()
        else:
            # Wilder's smoothing
            self._up_avg = (
                self._up_avg * (period - 1) + up
            ) / period
            self._down_avg = (
                self._down_avg * (period - 1) + down
            ) / period
            self._set_rsi()

    def _set_rsi(self) -> None:
        if self._down_avg == 0:
            if self._up_avg == 0:
                self.lines.rsi[0] = 50.0
            else:
                self.lines.rsi[0] = 100.0
        else:
            rs = self._up_avg / self._down_avg
            self.lines.rsi[0] = 100.0 - 100.0 / (1.0 + rs)


RelativeStrengthIndex = RSI


# ---------------------------------------------------------------------------
# Stochastic
# ---------------------------------------------------------------------------


class Stochastic(Indicator):
    """Stochastic Oscillator (%K and %D).

    %K = 100 * (close - lowest_low) / (highest_high - lowest_low)
    %D = SMA(%K, period_dfast)

    Lines: percK, percD
    """

    lines = ("percK", "percD")
    params = (
        ("period", 14),
        ("period_dfast", 3),
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.addminperiod(self.p.period)
        self._k_buffer = LineBuffer(name="stoch_k_internal")
        self._d_ema = _RollingSMA(self.p.period_dfast)

    def next(self) -> None:
        period = self.p.period

        high_line = _get_line(self.data, "high")
        low_line = _get_line(self.data, "low")
        close_line = _get_input_line(self.data)

        if high_line is None or low_line is None:
            high_line = close_line
            low_line = close_line

        # Highest high and lowest low over period
        highest = high_line[0]
        lowest = low_line[0]
        for i in range(1, period):
            h = high_line[-i]
            l = low_line[-i]
            if h > highest:
                highest = h
            if l < lowest:
                lowest = l

        diff = highest - lowest
        if diff != 0:
            k = 100.0 * (close_line[0] - lowest) / diff
        else:
            k = 50.0

        self.lines.percK[0] = k
        self._k_buffer.forward()
        self._k_buffer[0] = k

        d = self._d_ema.step(k)
        self.lines.percD[0] = d


class StochasticFull(Indicator):
    """Full Stochastic Oscillator with additional smoothing.

    Adds a second smoothing pass:
    %K = SMA(fast %K, period_dfast)
    %D = SMA(%K, period_dslow)

    Lines: percK, percD
    """

    lines = ("percK", "percD")
    params = (
        ("period", 14),
        ("period_dfast", 3),
        ("period_dslow", 3),
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.addminperiod(self.p.period)
        self._fast_k_sma = _RollingSMA(self.p.period_dfast)
        self._slow_d_sma = _RollingSMA(self.p.period_dslow)

    def next(self) -> None:
        period = self.p.period

        high_line = _get_line(self.data, "high")
        low_line = _get_line(self.data, "low")
        close_line = _get_input_line(self.data)

        if high_line is None or low_line is None:
            high_line = close_line
            low_line = close_line

        highest = high_line[0]
        lowest = low_line[0]
        for i in range(1, period):
            h = high_line[-i]
            l = low_line[-i]
            if h > highest:
                highest = h
            if l < lowest:
                lowest = l

        diff = highest - lowest
        if diff != 0:
            raw_k = 100.0 * (close_line[0] - lowest) / diff
        else:
            raw_k = 50.0

        # Smoothed %K
        k = self._fast_k_sma.step(raw_k)
        self.lines.percK[0] = k

        # %D
        d = self._slow_d_sma.step(k)
        self.lines.percD[0] = d


# ---------------------------------------------------------------------------
# WilliamsR
# ---------------------------------------------------------------------------


class WilliamsR(Indicator):
    """Williams %R oscillator.

    %R = -100 * (highest_high - close) / (highest_high - lowest_low)

    Ranges from -100 to 0 (overbought near 0, oversold near -100).
    """

    lines = ("percR",)
    params = (("period", 14),)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.addminperiod(self.p.period)

    def next(self) -> None:
        period = self.p.period

        high_line = _get_line(self.data, "high")
        low_line = _get_line(self.data, "low")
        close_line = _get_input_line(self.data)

        if high_line is None or low_line is None:
            high_line = close_line
            low_line = close_line

        highest = high_line[0]
        lowest = low_line[0]
        for i in range(1, period):
            h = high_line[-i]
            l = low_line[-i]
            if h > highest:
                highest = h
            if l < lowest:
                lowest = l

        diff = highest - lowest
        if diff != 0:
            self.lines.percR[0] = -100.0 * (highest - close_line[0]) / diff
        else:
            self.lines.percR[0] = -50.0


# ---------------------------------------------------------------------------
# UltimateOscillator
# ---------------------------------------------------------------------------


class UltimateOscillator(Indicator):
    """Ultimate Oscillator using three timeframes.

    UO = 100 * (4*BP_avg1 + 2*BP_avg2 + BP_avg3) / 7

    where BP = close - min(low, prev_close)
    and TR = max(high, prev_close) - min(low, prev_close).
    """

    lines = ("uo",)
    params = (
        ("p1", 7),
        ("p2", 14),
        ("p3", 28),
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # Need prev close + longest period
        self._minperiod = self.p.p3 + 1

        self._bp_vals: list[float] = []
        self._tr_vals: list[float] = []

    def next(self) -> None:
        high_line = _get_line(self.data, "high")
        low_line = _get_line(self.data, "low")
        close_line = _get_input_line(self.data)

        if high_line is None or low_line is None:
            high_line = close_line
            low_line = close_line

        prev_c = close_line[-1]
        h = high_line[0]
        l = low_line[0]

        bp = close_line[0] - min(l, prev_c)
        tr = max(h, prev_c) - min(l, prev_c)

        self._bp_vals.append(bp)
        self._tr_vals.append(tr)

        # Keep only as many values as the longest period
        max_len = self.p.p3
        if len(self._bp_vals) > max_len:
            self._bp_vals = self._bp_vals[-max_len:]
            self._tr_vals = self._tr_vals[-max_len:]

        p1, p2, p3 = self.p.p1, self.p.p2, self.p.p3

        bp1 = sum(self._bp_vals[-p1:])
        tr1 = sum(self._tr_vals[-p1:])
        bp2 = sum(self._bp_vals[-p2:])
        tr2 = sum(self._tr_vals[-p2:])
        bp3 = sum(self._bp_vals[-p3:])
        tr3 = sum(self._tr_vals[-p3:])

        avg1 = bp1 / tr1 if tr1 != 0 else 0.0
        avg2 = bp2 / tr2 if tr2 != 0 else 0.0
        avg3 = bp3 / tr3 if tr3 != 0 else 0.0

        self.lines.uo[0] = 100.0 * (4.0 * avg1 + 2.0 * avg2 + avg3) / 7.0


# ---------------------------------------------------------------------------
# CCI -- Commodity Channel Index
# ---------------------------------------------------------------------------


class CCI(Indicator):
    """Commodity Channel Index.

    CCI = (TP - SMA(TP)) / (0.015 * MeanDeviation(TP))
    where TP = (high + low + close) / 3.
    """

    lines = ("cci",)
    params = (
        ("period", 14),
        ("factor", 0.015),
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.addminperiod(self.p.period)
        self._tp_vals: list[float] = []

    def next(self) -> None:
        high_line = _get_line(self.data, "high")
        low_line = _get_line(self.data, "low")
        close_line = _get_input_line(self.data)

        if high_line is None or low_line is None:
            tp = close_line[0]
        else:
            tp = (high_line[0] + low_line[0] + close_line[0]) / 3.0

        self._tp_vals.append(tp)
        period = self.p.period
        if len(self._tp_vals) > period:
            self._tp_vals = self._tp_vals[-period:]

        tp_sma = sum(self._tp_vals[-period:]) / period
        mean_dev = sum(abs(v - tp_sma) for v in self._tp_vals[-period:]) / period

        if mean_dev != 0:
            self.lines.cci[0] = (tp - tp_sma) / (self.p.factor * mean_dev)
        else:
            self.lines.cci[0] = 0.0


CommodityChannelIndex = CCI


# ---------------------------------------------------------------------------
# MomentumOscillator
# ---------------------------------------------------------------------------


class MomentumOscillator(Indicator):
    """Momentum: close[0] - close[-period]."""

    lines = ("momentum",)
    params = (("period", 12),)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.addminperiod(self.p.period + 1)

    def next(self) -> None:
        src = _get_input_line(self.data)
        self.lines.momentum[0] = src[0] - src[-self.p.period]


# ---------------------------------------------------------------------------
# RateOfChange (ROC)
# ---------------------------------------------------------------------------


class RateOfChange(Indicator):
    """Rate of Change: 100 * (close[0] - close[-period]) / close[-period]."""

    lines = ("roc",)
    params = (("period", 12),)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.addminperiod(self.p.period + 1)

    def next(self) -> None:
        src = _get_input_line(self.data)
        prev = src[-self.p.period]
        if prev != 0:
            self.lines.roc[0] = 100.0 * (src[0] - prev) / prev
        else:
            self.lines.roc[0] = 0.0


ROC = RateOfChange


# ---------------------------------------------------------------------------
# DPO -- Detrended Price Oscillator
# ---------------------------------------------------------------------------


class DetrendedPriceOscillator(Indicator):
    """Detrended Price Oscillator.

    DPO = price - SMA(price, period) shifted by period/2 + 1 bars.
    """

    lines = ("dpo",)
    params = (("period", 20),)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._sma = SMA(self.data, period=self.p.period)
        self._lag = self.p.period // 2 + 1
        self.addminperiod(self.p.period + self._lag)

    def next(self) -> None:
        _step_indicator(self._sma)
        src = _get_input_line(self.data)
        self.lines.dpo[0] = src[-self._lag] - self._sma.lines.av[0]


DPO = DetrendedPriceOscillator


# ---------------------------------------------------------------------------
# PPO -- Percentage Price Oscillator
# ---------------------------------------------------------------------------


class PercentagePriceOscillator(Indicator):
    """Percentage Price Oscillator.

    PPO = 100 * (EMA(fast) - EMA(slow)) / EMA(slow)
    """

    lines = ("ppo", "signal", "histo")
    params = (
        ("period_me1", 12),
        ("period_me2", 26),
        ("period_signal", 9),
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._ema_fast = MovAv.EMA(self.data, period=self.p.period_me1)
        self._ema_slow = MovAv.EMA(self.data, period=self.p.period_me2)
        self._signal_sma = _RollingSMA(self.p.period_signal)
        self._minperiod = self.p.period_me2 + self.p.period_signal

    def next(self) -> None:
        _step_indicator(self._ema_fast)
        _step_indicator(self._ema_slow)

        slow = self._ema_slow.lines.av[0]
        if slow == 0:
            ppo = 0.0
        else:
            ppo = 100.0 * (self._ema_fast.lines.av[0] - slow) / slow

        self.lines.ppo[0] = ppo
        signal = self._signal_sma.step(ppo)
        self.lines.signal[0] = signal
        self.lines.histo[0] = ppo - signal


PPO = PercentagePriceOscillator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _RollingSMA:
    """Lightweight rolling SMA that processes values one at a time."""

    def __init__(self, period: int) -> None:
        self._period = period
        self._values: list[float] = []

    def step(self, value: float) -> float:
        """Add a value and return the current SMA."""
        self._values.append(value)
        if len(self._values) > self._period:
            self._values = self._values[-self._period:]
        return sum(self._values) / len(self._values)


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
