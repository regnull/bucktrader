"""Volume indicators: OBV, AccumDist, MFI, VWAP."""

from __future__ import annotations

from typing import Any

from bucktrader.dataseries import LineBuffer
from bucktrader.indicator import Indicator
from bucktrader.indicators.basicops import _get_input_line


class OnBalanceVolume(Indicator):
    """On-Balance Volume."""

    lines = ("obv",)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.addminperiod(2)
        self._obv = 0.0

    def next(self) -> None:
        close = _get_input_line(self.data)
        volume = _get_line(self.data, "volume")
        vol = volume[0] if volume is not None else 0.0
        if close[0] > close[-1]:
            self._obv += vol
        elif close[0] < close[-1]:
            self._obv -= vol
        self.lines.obv[0] = self._obv


OBV = OnBalanceVolume


class AccumDistIndex(Indicator):
    """Accumulation/Distribution Index."""

    lines = ("ad",)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._value = 0.0

    def next(self) -> None:
        high = _get_line(self.data, "high")
        low = _get_line(self.data, "low")
        close = _get_input_line(self.data)
        volume = _get_line(self.data, "volume")
        if high is None or low is None or volume is None:
            self.lines.ad[0] = self._value
            return

        hl = high[0] - low[0]
        if hl == 0:
            mfm = 0.0
        else:
            mfm = ((close[0] - low[0]) - (high[0] - close[0])) / hl
        self._value += mfm * volume[0]
        self.lines.ad[0] = self._value


AccumDist = AccumDistIndex


class MoneyFlowIndicator(Indicator):
    """Money Flow Index."""

    lines = ("mfi",)
    params = (("period", 14),)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.addminperiod(self.p.period + 1)
        self._pos: list[float] = []
        self._neg: list[float] = []

    def next(self) -> None:
        high = _get_line(self.data, "high")
        low = _get_line(self.data, "low")
        close = _get_input_line(self.data)
        volume = _get_line(self.data, "volume")
        if high is None or low is None or volume is None:
            self.lines.mfi[0] = 50.0
            return

        tp = (high[0] + low[0] + close[0]) / 3.0
        prev_tp = (high[-1] + low[-1] + close[-1]) / 3.0
        flow = tp * volume[0]
        if tp > prev_tp:
            self._pos.append(flow)
            self._neg.append(0.0)
        elif tp < prev_tp:
            self._pos.append(0.0)
            self._neg.append(flow)
        else:
            self._pos.append(0.0)
            self._neg.append(0.0)

        period = self.p.period
        if len(self._pos) > period:
            self._pos = self._pos[-period:]
            self._neg = self._neg[-period:]

        pos = sum(self._pos)
        neg = sum(self._neg)
        if neg == 0:
            self.lines.mfi[0] = 100.0 if pos > 0 else 50.0
            return
        mr = pos / neg
        self.lines.mfi[0] = 100.0 - 100.0 / (1.0 + mr)


MFI = MoneyFlowIndicator


class VolumeWeightedAveragePrice(Indicator):
    """Rolling VWAP over period."""

    lines = ("vwap",)
    params = (("period", 20),)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.addminperiod(self.p.period)
        self._tpv: list[float] = []
        self._vol: list[float] = []

    def next(self) -> None:
        high = _get_line(self.data, "high")
        low = _get_line(self.data, "low")
        close = _get_input_line(self.data)
        volume = _get_line(self.data, "volume")
        if high is None or low is None or volume is None:
            self.lines.vwap[0] = close[0]
            return

        tp = (high[0] + low[0] + close[0]) / 3.0
        self._tpv.append(tp * volume[0])
        self._vol.append(volume[0])
        period = self.p.period
        if len(self._tpv) > period:
            self._tpv = self._tpv[-period:]
            self._vol = self._vol[-period:]
        den = sum(self._vol)
        self.lines.vwap[0] = close[0] if den == 0 else sum(self._tpv) / den


VWAP = VolumeWeightedAveragePrice


def _get_line(data: Any, name: str) -> LineBuffer | None:
    line = getattr(data, name, None)
    if isinstance(line, LineBuffer):
        return line
    if hasattr(data, "_lines") and isinstance(data._lines, dict):
        return data._lines.get(name)
    return None
