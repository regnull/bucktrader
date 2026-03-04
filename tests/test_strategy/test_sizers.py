"""Tests for bucktrader.sizers module."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from bucktrader.comminfo import CommInfoBase
from bucktrader.broker import BackBroker
from bucktrader.position import Position
from bucktrader.sizers import (
    AllInSizer,
    AllInSizerInt,
    FixedReverser,
    FixedSize,
    PercentSizer,
    PercentSizerInt,
    Sizer,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class MockData:
    """Mock data feed with a close price."""

    def __init__(self, close: float = 100.0, name: str = "TEST"):
        self.close = _IndexableValue(close)
        self.name = name


class _IndexableValue:
    """A value accessible via [0] indexing."""

    def __init__(self, value: float):
        self._value = value

    def __getitem__(self, index: int) -> float:
        return self._value

    def __float__(self) -> float:
        return self._value


def make_comminfo(stocklike: bool = True) -> CommInfoBase:
    """Create a stock-like or futures-like CommInfoBase."""
    return CommInfoBase(stocklike=stocklike)


# ---------------------------------------------------------------------------
# Sizer base class
# ---------------------------------------------------------------------------


class TestSizerBase:
    def test_base_raises_not_implemented(self):
        sizer = Sizer()
        with pytest.raises(NotImplementedError):
            sizer.getsizing(make_comminfo(), 10000.0, MockData(), True)

    def test_params_access(self):
        class MySizer(Sizer):
            params = (("stake", 42),)

            def _getsizing(self, comminfo, cash, data, isbuy):
                return self.p.stake

        sizer = MySizer()
        assert sizer.p.stake == 42

    def test_params_override(self):
        class MySizer(Sizer):
            params = (("stake", 42),)

            def _getsizing(self, comminfo, cash, data, isbuy):
                return self.p.stake

        sizer = MySizer(stake=100)
        assert sizer.p.stake == 100

    def test_unexpected_kwargs_raises(self):
        with pytest.raises(TypeError, match="Unexpected keyword"):
            FixedSize(nonexistent=5)

    def test_strategy_and_broker_attrs(self):
        sizer = Sizer()
        assert sizer.strategy is None
        assert sizer.broker is None


# ---------------------------------------------------------------------------
# FixedSize
# ---------------------------------------------------------------------------


class TestFixedSize:
    def test_default_stake(self):
        sizer = FixedSize()
        size = sizer.getsizing(make_comminfo(), 10000.0, MockData(), True)
        assert size == 1

    def test_custom_stake(self):
        sizer = FixedSize(stake=50)
        size = sizer.getsizing(make_comminfo(), 10000.0, MockData(), True)
        assert size == 50

    def test_buy_and_sell_same_size(self):
        sizer = FixedSize(stake=10)
        buy_size = sizer.getsizing(make_comminfo(), 10000.0, MockData(), True)
        sell_size = sizer.getsizing(make_comminfo(), 10000.0, MockData(), False)
        assert buy_size == sell_size == 10


# ---------------------------------------------------------------------------
# FixedReverser
# ---------------------------------------------------------------------------


class TestFixedReverser:
    def test_flat_position_returns_stake(self):
        broker = BackBroker()
        broker.start()
        sizer = FixedReverser(stake=10)
        sizer.broker = broker

        data = MockData()
        size = sizer.getsizing(make_comminfo(), 10000.0, data, True)
        assert size == 10

    def test_reversal_doubles_stake(self):
        """When reversing from long to short, size should double."""
        broker = BackBroker()
        broker.start()
        data = MockData()

        # Manually create a long position.
        pos = broker.getposition(data)
        pos.update(10, 100.0)

        sizer = FixedReverser(stake=10)
        sizer.broker = broker

        # Selling when long -> reversal -> double stake.
        size = sizer.getsizing(make_comminfo(), 10000.0, data, False)
        assert size == 20

    def test_same_direction_returns_stake(self):
        """When adding to position, size should be the normal stake."""
        broker = BackBroker()
        broker.start()
        data = MockData()

        pos = broker.getposition(data)
        pos.update(10, 100.0)

        sizer = FixedReverser(stake=10)
        sizer.broker = broker

        # Buying when already long -> same direction -> normal stake.
        size = sizer.getsizing(make_comminfo(), 10000.0, data, True)
        assert size == 10

    def test_reversal_from_short(self):
        """When reversing from short to long, size should double."""
        broker = BackBroker()
        broker.start()
        data = MockData()

        pos = broker.getposition(data)
        pos.update(-5, 100.0)

        sizer = FixedReverser(stake=5)
        sizer.broker = broker

        # Buying when short -> reversal -> double.
        size = sizer.getsizing(make_comminfo(), 10000.0, data, True)
        assert size == 10

    def test_no_broker_returns_stake(self):
        """Without a broker, should return normal stake (flat assumption)."""
        sizer = FixedReverser(stake=10)
        size = sizer.getsizing(make_comminfo(), 10000.0, MockData(), True)
        assert size == 10


# ---------------------------------------------------------------------------
# PercentSizer
# ---------------------------------------------------------------------------


class TestPercentSizer:
    def test_default_percent(self):
        sizer = PercentSizer()
        # Default 20%, cash=10000, price=100 -> 20% of 10000 = 2000 / 100 = 20
        size = sizer.getsizing(make_comminfo(), 10000.0, MockData(close=100.0), True)
        assert size == 20.0

    def test_custom_percent(self):
        sizer = PercentSizer(percents=50)
        # 50% of 10000 = 5000 / 100 = 50
        size = sizer.getsizing(make_comminfo(), 10000.0, MockData(close=100.0), True)
        assert size == 50.0

    def test_low_cash(self):
        sizer = PercentSizer(percents=20)
        # 20% of 500 = 100 / 100 = 1
        size = sizer.getsizing(make_comminfo(), 500.0, MockData(close=100.0), True)
        assert size == 1.0

    def test_zero_price_returns_zero(self):
        sizer = PercentSizer(percents=50)
        size = sizer.getsizing(make_comminfo(), 10000.0, MockData(close=0.0), True)
        assert size == 0.0


# ---------------------------------------------------------------------------
# AllInSizer
# ---------------------------------------------------------------------------


class TestAllInSizer:
    def test_all_in(self):
        sizer = AllInSizer()
        # 100% of 10000 / 100 = 100
        size = sizer.getsizing(make_comminfo(), 10000.0, MockData(close=100.0), True)
        assert size == 100.0

    def test_inherits_percent_sizer(self):
        assert issubclass(AllInSizer, PercentSizer)


# ---------------------------------------------------------------------------
# PercentSizerInt
# ---------------------------------------------------------------------------


class TestPercentSizerInt:
    def test_truncates_to_int(self):
        sizer = PercentSizerInt(percents=30)
        # 30% of 10000 = 3000. At price 70 -> 3000/70 = 42.857... -> 42
        size = sizer.getsizing(make_comminfo(), 10000.0, MockData(close=70.0), True)
        assert size == 42.0
        assert size == int(size)

    def test_default_percent(self):
        sizer = PercentSizerInt()
        # Default 20%, cash=10000, price=100 -> 2000/100 = 20 (already int)
        size = sizer.getsizing(make_comminfo(), 10000.0, MockData(close=100.0), True)
        assert size == 20.0


# ---------------------------------------------------------------------------
# AllInSizerInt
# ---------------------------------------------------------------------------


class TestAllInSizerInt:
    def test_all_in_truncated(self):
        sizer = AllInSizerInt()
        # 100% of 10000 / 70 = 142.857... -> 142
        size = sizer.getsizing(make_comminfo(), 10000.0, MockData(close=70.0), True)
        assert size == 142.0
        assert size == int(size)

    def test_inherits_all_in(self):
        assert issubclass(AllInSizerInt, AllInSizer)
