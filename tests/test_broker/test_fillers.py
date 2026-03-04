"""Tests for bucktrader.fillers module."""

import pytest

from bucktrader.fillers import BarPointPerc, FixedBarPerc, FixedSize


class MockOrderData:
    """Minimal mock for order.executed."""

    def __init__(self, remsize: float = 100.0):
        self.remsize = remsize


class MockData:
    """Minimal mock for a data feed with OHLCV fields."""

    def __init__(
        self,
        open: float = 100.0,
        high: float = 110.0,
        low: float = 90.0,
        close: float = 105.0,
        volume: float = 1000.0,
    ):
        self.open = open
        self.high = high
        self.low = low
        self.close = close
        self.volume = volume


class MockOrder:
    """Minimal mock for an order."""

    def __init__(
        self,
        remsize: float = 100.0,
        data: MockData | None = None,
    ):
        self.executed = MockOrderData(remsize=remsize)
        self.data = data or MockData()


# ── FixedSize ─────────────────────────────────────────────────────────


class TestFixedSize:
    def test_fills_up_to_size(self):
        filler = FixedSize(size=50)
        order = MockOrder(remsize=100, data=MockData(volume=1000))
        assert filler(order, 100.0) == 50

    def test_limited_by_volume(self):
        filler = FixedSize(size=200)
        order = MockOrder(remsize=500, data=MockData(volume=100))
        assert filler(order, 100.0) == 100

    def test_limited_by_remaining(self):
        filler = FixedSize(size=200)
        order = MockOrder(remsize=30, data=MockData(volume=1000))
        assert filler(order, 100.0) == 30

    def test_minimum_of_all(self):
        filler = FixedSize(size=50)
        order = MockOrder(remsize=30, data=MockData(volume=40))
        assert filler(order, 100.0) == 30

    def test_invalid_size_raises(self):
        with pytest.raises(ValueError, match="positive"):
            FixedSize(size=0)
        with pytest.raises(ValueError, match="positive"):
            FixedSize(size=-10)

    def test_no_data_volume_returns_zero(self):
        filler = FixedSize(size=50)
        order = MockOrder(remsize=100)
        order.data = None
        assert filler(order, 100.0) == 0.0


# ── FixedBarPerc ──────────────────────────────────────────────────────


class TestFixedBarPerc:
    def test_full_bar_volume(self):
        filler = FixedBarPerc(perc=1.0)
        order = MockOrder(remsize=2000, data=MockData(volume=1000))
        assert filler(order, 100.0) == 1000

    def test_half_bar_volume(self):
        filler = FixedBarPerc(perc=0.5)
        order = MockOrder(remsize=2000, data=MockData(volume=1000))
        assert filler(order, 100.0) == 500

    def test_limited_by_remaining(self):
        filler = FixedBarPerc(perc=1.0)
        order = MockOrder(remsize=50, data=MockData(volume=1000))
        assert filler(order, 100.0) == 50

    def test_invalid_perc_raises(self):
        with pytest.raises(ValueError):
            FixedBarPerc(perc=0.0)
        with pytest.raises(ValueError):
            FixedBarPerc(perc=1.5)
        with pytest.raises(ValueError):
            FixedBarPerc(perc=-0.1)


# ── BarPointPerc ──────────────────────────────────────────────────────


class TestBarPointPerc:
    def test_with_price_range(self):
        # Volume=1000, range=110-90=20, per-point=50, perc=1.0 -> 50.
        filler = BarPointPerc(perc=1.0)
        order = MockOrder(
            remsize=200, data=MockData(high=110, low=90, volume=1000)
        )
        assert filler(order, 100.0) == pytest.approx(50.0)

    def test_half_perc(self):
        filler = BarPointPerc(perc=0.5)
        order = MockOrder(
            remsize=200, data=MockData(high=110, low=90, volume=1000)
        )
        assert filler(order, 100.0) == pytest.approx(25.0)

    def test_doji_bar(self):
        """When high == low, all volume at that price point."""
        filler = BarPointPerc(perc=1.0)
        order = MockOrder(
            remsize=2000, data=MockData(high=100, low=100, volume=500)
        )
        assert filler(order, 100.0) == pytest.approx(500.0)

    def test_limited_by_remaining(self):
        filler = BarPointPerc(perc=1.0)
        order = MockOrder(
            remsize=10, data=MockData(high=110, low=90, volume=1000)
        )
        # per-point = 50, but remaining = 10.
        assert filler(order, 100.0) == pytest.approx(10.0)

    def test_invalid_perc_raises(self):
        with pytest.raises(ValueError):
            BarPointPerc(perc=0.0)
        with pytest.raises(ValueError):
            BarPointPerc(perc=2.0)
