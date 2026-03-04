"""Tests for indicator library coverage (TER-396)."""

from __future__ import annotations

import math

import pytest

from bucktrader.dataseries import LineBuffer
from bucktrader.indicators import (
    ATR,
    CCI,
    DPO,
    EMA,
    HMA,
    MACD,
    MFI,
    OBV,
    PPO,
    ROC,
    RSI,
    SMA,
    VWAP,
    BollingerBands,
    Envelope,
    HeikinAshi,
    Ichimoku,
    ParabolicSAR,
    PivotPoint,
    ZigZag,
)


class FakeOHLCVData:
    _line_names = ("open", "high", "low", "close", "volume")

    def __init__(self) -> None:
        self.open = LineBuffer(name="open")
        self.high = LineBuffer(name="high")
        self.low = LineBuffer(name="low")
        self.close = LineBuffer(name="close")
        self.volume = LineBuffer(name="volume")
        self._lines = {
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
        }
        self._minperiod = 1

    def push(self, o: float, h: float, l: float, c: float, v: float) -> None:
        for line in self._lines.values():
            line.forward()
        self.open[0] = o
        self.high[0] = h
        self.low[0] = l
        self.close[0] = c
        self.volume[0] = v


def _step(ind, data: FakeOHLCVData, bar: tuple[float, float, float, float, float]):
    data.push(*bar)
    ind.lines.forward()
    ind.next()


class TestMovingAverages:
    def test_sma_known_value(self):
        data = FakeOHLCVData()
        ind = SMA(data, period=3)
        for bar in [
            (1, 1, 1, 1, 1),
            (2, 2, 2, 2, 1),
            (3, 3, 3, 3, 1),
        ]:
            _step(ind, data, bar)
        assert ind.lines.av[0] == pytest.approx(2.0)

    def test_ema_constant_series(self):
        data = FakeOHLCVData()
        ind = EMA(data, period=3)
        for _ in range(8):
            _step(ind, data, (10, 10, 10, 10, 1))
        assert ind.lines.av[0] == pytest.approx(10.0)

    def test_hma_runs(self):
        data = FakeOHLCVData()
        ind = HMA(data, period=5)
        for i in range(12):
            x = float(i + 1)
            _step(ind, data, (x, x + 1, x - 1, x, 1))
        assert not math.isnan(ind.lines.av[0])


class TestTrend:
    def test_macd_flat_market_near_zero(self):
        data = FakeOHLCVData()
        ind = MACD(data)
        for _ in range(40):
            _step(ind, data, (100, 101, 99, 100, 1000))
        assert ind.lines.macd[0] == pytest.approx(0.0, abs=1e-9)

    def test_parabolic_sar_runs(self):
        data = FakeOHLCVData()
        ind = ParabolicSAR(data)
        for i in range(20):
            x = 100 + i
            _step(ind, data, (x - 0.5, x + 1.0, x - 1.0, x, 1000))
        assert not math.isnan(ind.lines.psar[0])

    def test_ichimoku_tenkan(self):
        data = FakeOHLCVData()
        ind = Ichimoku(data, tenkan=3, kijun=3, senkou=3)
        bars = [
            (0, 10, 8, 9, 1),
            (0, 11, 7, 9, 1),
            (0, 12, 6, 9, 1),
        ]
        for bar in bars:
            _step(ind, data, bar)
        # midpoint of highest high=12 and lowest low=6
        assert ind.lines.tenkan[0] == pytest.approx(9.0)


class TestOscillators:
    def test_rsi_rising_series_high(self):
        data = FakeOHLCVData()
        ind = RSI(data, period=5)
        for i in range(1, 20):
            x = float(i)
            _step(ind, data, (x, x, x, x, 1))
        assert ind.lines.rsi[0] > 90.0

    def test_roc(self):
        data = FakeOHLCVData()
        ind = ROC(data, period=3)
        for c in [10, 10, 10, 11]:
            _step(ind, data, (c, c, c, c, 1))
        assert ind.lines.roc[0] == pytest.approx(10.0)

    def test_dpo_and_ppo_run(self):
        data = FakeOHLCVData()
        dpo = DPO(data, period=6)
        ppo = PPO(data)
        for i in range(50):
            c = 100.0 + i * 0.2
            bar = (c, c + 1, c - 1, c, 1000)
            _step(dpo, data, bar)
            # PPO reads same advancing data too.
            ppo.lines.forward()
            ppo.next()
        assert not math.isnan(dpo.lines.dpo[0])
        assert not math.isnan(ppo.lines.ppo[0])


class TestVolatility:
    def test_bbands_constant(self):
        data = FakeOHLCVData()
        ind = BollingerBands(data, period=5, devfactor=2.0)
        for _ in range(8):
            _step(ind, data, (100, 100, 100, 100, 1))
        assert ind.lines.mid[0] == pytest.approx(100.0)
        assert ind.lines.top[0] == pytest.approx(100.0)
        assert ind.lines.bot[0] == pytest.approx(100.0)

    def test_atr_positive(self):
        data = FakeOHLCVData()
        ind = ATR(data, period=3)
        for i in range(1, 10):
            c = float(i * 10)
            _step(ind, data, (c - 1, c + 2, c - 3, c, 100))
        assert ind.lines.atr[0] >= 0

    def test_cci_runs(self):
        data = FakeOHLCVData()
        ind = CCI(data, period=5)
        for i in range(1, 20):
            c = float(i)
            _step(ind, data, (c - 0.5, c + 1, c - 1, c, 10))
        assert not math.isnan(ind.lines.cci[0])


class TestVolume:
    def test_obv_known_sequence(self):
        data = FakeOHLCVData()
        ind = OBV(data)
        closes = [10, 11, 10, 12]
        vols = [100, 50, 70, 40]
        for c, v in zip(closes, vols):
            _step(ind, data, (c, c, c, c, v))
        # +50 -70 +40 = 20
        assert ind.lines.obv[0] == pytest.approx(20.0)

    def test_mfi_and_vwap_run(self):
        data = FakeOHLCVData()
        mfi = MFI(data, period=3)
        vwap = VWAP(data, period=3)
        for i in range(1, 12):
            c = float(100 + i)
            bar = (c - 0.5, c + 1.0, c - 1.0, c, float(10 * i))
            _step(mfi, data, bar)
            vwap.lines.forward()
            vwap.next()
        assert 0.0 <= mfi.lines.mfi[0] <= 100.0
        assert not math.isnan(vwap.lines.vwap[0])


class TestOtherIndicators:
    def test_pivot_point(self):
        data = FakeOHLCVData()
        ind = PivotPoint(data)
        _step(ind, data, (9, 10, 8, 9, 1))
        _step(ind, data, (10, 11, 9, 10, 1))
        # From previous bar: (10 + 8 + 9) / 3 = 9
        assert ind.lines.p[0] == pytest.approx(9.0)

    def test_heikinashi(self):
        data = FakeOHLCVData()
        ind = HeikinAshi(data)
        _step(ind, data, (10, 12, 9, 11, 1))
        assert ind.lines.ha_close[0] == pytest.approx((10 + 12 + 9 + 11) / 4.0)

    def test_zigzag_and_envelope(self):
        data = FakeOHLCVData()
        zz = ZigZag(data, retrace=2.0)
        env = Envelope(data, period=3, perc=1.0)
        for i in range(1, 15):
            c = float(100 + i)
            bar = (c - 0.5, c + 1, c - 1, c, 10)
            _step(zz, data, bar)
            env.lines.forward()
            env.next()
        assert not math.isnan(zz.lines.zigzag[0])
        assert env.lines.top[0] > env.lines.mid[0] > env.lines.bot[0]
