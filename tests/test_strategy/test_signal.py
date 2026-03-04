"""Tests for bucktrader.signal module and signal-based trading."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from bucktrader.broker import BackBroker
from bucktrader.order import ExecType, OrderStatus, reset_order_ref_counter
from bucktrader.signal import (
    SIGNAL_LONG,
    SIGNAL_LONGSHORT,
    SIGNAL_LONGEXIT,
    SIGNAL_SHORT,
    SIGNAL_SHORTEXIT,
    SIGNAL_LONG_INV,
    SIGNAL_LONG_ANY,
    SIGNAL_SHORT_INV,
    SIGNAL_SHORT_ANY,
    Signal,
    SignalStrategy,
    SignalType,
)
from bucktrader.strategy import Strategy
from bucktrader.trade import reset_trade_ref_counter


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_refs():
    """Reset global counters for deterministic tests."""
    reset_order_ref_counter(1)
    reset_trade_ref_counter(1)
    yield
    reset_order_ref_counter(1)
    reset_trade_ref_counter(1)


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


class MockIndicator:
    """A mock indicator that returns a configurable signal value."""

    def __init__(self, value: float = 0.0):
        self._value = value

    def __getitem__(self, index: int) -> float:
        return self._value

    def set_value(self, value: float) -> None:
        self._value = value


class MockDataFeed:
    """A mock data feed for testing."""

    def __init__(self, close: float = 100.0, name: str = "TEST"):
        self.name = name
        self._name = name
        self.open = _IndexableValue(close)
        self.high = _IndexableValue(close + 10)
        self.low = _IndexableValue(close - 10)
        self.close = _IndexableValue(close)
        self.volume = _IndexableValue(10000.0)
        self._line_names = ("close",)
        self._minperiod = 1


class _IndexableValue:
    def __init__(self, value: float):
        self._value = value

    def __getitem__(self, index: int) -> float:
        return self._value


def make_signal_strategy(
    cash: float = 10000.0,
    close: float = 100.0,
) -> Strategy:
    """Create a Strategy configured for signal testing."""
    broker = BackBroker(cash=cash)
    broker.start()
    data = MockDataFeed(close=close)

    strat = Strategy()
    strat.setdatas([data])
    strat.broker = broker
    strat._sizer.broker = broker

    return strat


# ---------------------------------------------------------------------------
# Signal type constants
# ---------------------------------------------------------------------------


class TestSignalTypeConstants:
    def test_longshort(self):
        assert SignalType.LONGSHORT == 0

    def test_long(self):
        assert SignalType.LONG == 1

    def test_short(self):
        assert SignalType.SHORT == 4

    def test_longexit(self):
        assert SignalType.LONGEXIT == 7

    def test_shortexit(self):
        assert SignalType.SHORTEXIT == 8

    def test_module_level_aliases(self):
        assert SIGNAL_LONGSHORT == SignalType.LONGSHORT
        assert SIGNAL_LONG == SignalType.LONG
        assert SIGNAL_SHORT == SignalType.SHORT
        assert SIGNAL_LONGEXIT == SignalType.LONGEXIT
        assert SIGNAL_SHORTEXIT == SignalType.SHORTEXIT


# ---------------------------------------------------------------------------
# Signal class
# ---------------------------------------------------------------------------


class TestSignal:
    def test_signal_creation(self):
        ind = MockIndicator(1.0)
        sig = Signal(SignalType.LONG, ind)
        assert sig.signal_type == SignalType.LONG
        assert sig.indicator is ind

    def test_get_value_positive(self):
        ind = MockIndicator(1.5)
        sig = Signal(SignalType.LONG, ind)
        assert sig.get_value() == 1.5

    def test_get_value_negative(self):
        ind = MockIndicator(-2.0)
        sig = Signal(SignalType.SHORT, ind)
        assert sig.get_value() == -2.0

    def test_get_value_zero(self):
        ind = MockIndicator(0.0)
        sig = Signal(SignalType.LONGSHORT, ind)
        assert sig.get_value() == 0.0


# ---------------------------------------------------------------------------
# SignalStrategy (used as mixin via Strategy)
# ---------------------------------------------------------------------------


class TestSignalAdd:
    def test_add_signal(self):
        strat = make_signal_strategy()
        ind = MockIndicator(1.0)
        strat.signal_add(SignalType.LONG, ind)

        assert len(strat._signals) == 1
        assert strat._signals[0].signal_type == SignalType.LONG

    def test_add_multiple_signals(self):
        strat = make_signal_strategy()
        strat.signal_add(SignalType.LONG, MockIndicator(1.0))
        strat.signal_add(SignalType.SHORT, MockIndicator(-1.0))
        strat.signal_add(SignalType.LONGEXIT, MockIndicator(0.5))

        assert len(strat._signals) == 3


# ---------------------------------------------------------------------------
# Signal processing
# ---------------------------------------------------------------------------


class TestSignalProcessing:
    def test_longshort_positive_buys(self):
        strat = make_signal_strategy()
        ind = MockIndicator(1.0)
        strat.signal_add(SignalType.LONGSHORT, ind)

        strat._process_signals()

        # Should have placed a buy order.
        assert len(strat._orders) == 1
        assert strat._orders[0].size > 0

    def test_longshort_negative_sells(self):
        strat = make_signal_strategy()
        ind = MockIndicator(-1.0)
        strat.signal_add(SignalType.LONGSHORT, ind)

        strat._process_signals()

        # Should have placed a sell order.
        assert len(strat._orders) == 1
        assert strat._orders[0].size < 0

    def test_long_signal_positive_buys(self):
        strat = make_signal_strategy()
        ind = MockIndicator(1.0)
        strat.signal_add(SignalType.LONG, ind)

        strat._process_signals()

        assert len(strat._orders) == 1
        assert strat._orders[0].size > 0

    def test_long_signal_negative_closes_long(self):
        strat = make_signal_strategy()

        # First create a long position.
        strat.buy(size=10)
        strat.broker.next()
        assert strat.position.size == 10

        # Now a negative LONG signal should close it.
        ind = MockIndicator(-1.0)
        strat.signal_add(SignalType.LONG, ind)
        strat._process_signals()

        # Should have a close order (sell to close the long).
        close_orders = [o for o in strat._orders if o.size < 0]
        assert len(close_orders) >= 1

    def test_longexit_closes_long(self):
        strat = make_signal_strategy()

        # Create a long position.
        strat.buy(size=10)
        strat.broker.next()
        assert strat.position.size == 10

        # LONGEXIT with positive value should close.
        ind = MockIndicator(1.0)
        strat.signal_add(SignalType.LONGEXIT, ind)
        strat._process_signals()

        close_orders = [o for o in strat._orders if o.size < 0]
        assert len(close_orders) >= 1

    def test_shortexit_closes_short(self):
        strat = make_signal_strategy()

        # Create a short position.
        strat.sell(size=10)
        strat.broker.next()
        assert strat.position.size == -10

        # SHORTEXIT with negative value should close.
        ind = MockIndicator(-1.0)
        strat.signal_add(SignalType.SHORTEXIT, ind)
        strat._process_signals()

        close_orders = [o for o in strat._orders if o.size > 0]
        assert len(close_orders) >= 1

    def test_zero_signal_no_orders(self):
        strat = make_signal_strategy()
        ind = MockIndicator(0.0)
        strat.signal_add(SignalType.LONGSHORT, ind)

        strat._process_signals()

        # Zero signal => no long_signal or short_signal accumulated.
        # No orders should be placed (both long_signal and short_signal are 0).
        assert len(strat._orders) == 0

    def test_concurrent_false_blocks_orders(self):
        strat = make_signal_strategy()
        strat._concurrent = False

        # Place a pending limit order (won't execute immediately).
        strat.buy(size=10, price=50.0, exectype=ExecType.Limit)

        # Now try signal processing -- should be blocked by pending order.
        ind = MockIndicator(1.0)
        strat.signal_add(SignalType.LONG, ind)
        strat._process_signals()

        # Only the original limit order should exist.
        assert len(strat._orders) == 1

    def test_concurrent_true_allows_orders(self):
        strat = make_signal_strategy()
        strat._concurrent = True

        # Place a pending limit order.
        strat.buy(size=10, price=50.0, exectype=ExecType.Limit)

        # Signal processing should still work.
        ind = MockIndicator(1.0)
        strat.signal_add(SignalType.LONG, ind)
        strat._process_signals()

        assert len(strat._orders) == 2

    def test_stake_override(self):
        strat = make_signal_strategy()
        strat._stake = 25

        ind = MockIndicator(1.0)
        strat.signal_add(SignalType.LONGSHORT, ind)
        strat._process_signals()

        assert len(strat._orders) == 1
        assert abs(strat._orders[0].size) == 25


# ---------------------------------------------------------------------------
# Signal type variants
# ---------------------------------------------------------------------------


class TestSignalVariants:
    def test_long_inv_negative_enters_long(self):
        strat = make_signal_strategy()
        ind = MockIndicator(-1.0)
        strat.signal_add(SignalType.LONG_INV, ind)

        strat._process_signals()

        assert len(strat._orders) == 1
        assert strat._orders[0].size > 0

    def test_long_inv_positive_exits_long(self):
        strat = make_signal_strategy()

        # Create long position first.
        strat.buy(size=10)
        strat.broker.next()

        ind = MockIndicator(1.0)
        strat.signal_add(SignalType.LONG_INV, ind)
        strat._process_signals()

        # Should have a close order.
        close_orders = [o for o in strat._orders if o.size < 0]
        assert len(close_orders) >= 1

    def test_short_signal_negative_enters_short(self):
        strat = make_signal_strategy()
        ind = MockIndicator(-1.0)
        strat.signal_add(SignalType.SHORT, ind)

        strat._process_signals()

        assert len(strat._orders) == 1
        assert strat._orders[0].size < 0

    def test_short_inv_positive_enters_short(self):
        strat = make_signal_strategy()
        ind = MockIndicator(1.0)
        strat.signal_add(SignalType.SHORT_INV, ind)

        strat._process_signals()

        assert len(strat._orders) == 1
        assert strat._orders[0].size < 0

    def test_long_any_positive_enters_long(self):
        strat = make_signal_strategy()
        ind = MockIndicator(1.0)
        strat.signal_add(SignalType.LONG_ANY, ind)

        strat._process_signals()

        assert len(strat._orders) == 1
        assert strat._orders[0].size > 0

    def test_short_any_negative_enters_short(self):
        strat = make_signal_strategy()
        ind = MockIndicator(-1.0)
        strat.signal_add(SignalType.SHORT_ANY, ind)

        strat._process_signals()

        assert len(strat._orders) == 1
        assert strat._orders[0].size < 0


# ---------------------------------------------------------------------------
# Accumulate mode
# ---------------------------------------------------------------------------


class TestAccumulateMode:
    def test_no_accumulate_blocks_second_buy(self):
        strat = make_signal_strategy()
        strat._accumulate = False

        # Create a long position.
        strat.buy(size=10)
        strat.broker.next()
        assert strat.position.size == 10

        # A LONG signal should not add to position when _accumulate=False.
        ind = MockIndicator(1.0)
        strat.signal_add(SignalType.LONG, ind)
        strat._process_signals()

        # No new buy order should be created.
        buy_orders = [o for o in strat._orders if o.size > 0]
        assert len(buy_orders) == 1  # Only the original buy.

    def test_accumulate_allows_second_buy(self):
        strat = make_signal_strategy()
        strat._accumulate = True

        # Create a long position.
        strat.buy(size=10)
        strat.broker.next()
        assert strat.position.size == 10

        # With accumulate, a LONG signal should add to position.
        ind = MockIndicator(1.0)
        strat.signal_add(SignalType.LONG, ind)
        strat._process_signals()

        buy_orders = [o for o in strat._orders if o.size > 0]
        assert len(buy_orders) == 2  # Original + accumulated.
