"""Comprehensive tests for bucktrader.strategy module."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from bucktrader.broker import BackBroker
from bucktrader.order import ExecType, Order, OrderStatus, reset_order_ref_counter
from bucktrader.position import Position
from bucktrader.sizers import FixedSize, PercentSizer, Sizer
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


class MockDataFeed:
    """A mock data feed with OHLCV lines accessible via indexing.

    Supports both ``data.close[0]`` and ``data.close`` (as a scalar).
    Also has a ``name`` attribute and ``_name`` for named-feed lookups.
    """

    def __init__(
        self,
        name: str = "TEST",
        open: float = 100.0,
        high: float = 110.0,
        low: float = 90.0,
        close: float = 105.0,
        volume: float = 10000.0,
    ):
        self.name = name
        self._name = name
        self.open = _MockLine(open)
        self.high = _MockLine(high)
        self.low = _MockLine(low)
        self.close = _MockLine(close)
        self.volume = _MockLine(volume)
        self._line_names = ("open", "high", "low", "close", "volume")
        self._minperiod = 1


class _MockLine:
    """A mock line that supports indexing: line[0] returns the value."""

    def __init__(self, value: float):
        self._value = value

    def __getitem__(self, index: int) -> float:
        return self._value

    def __float__(self) -> float:
        return self._value


def make_data(**kwargs: Any) -> MockDataFeed:
    """Convenience factory for MockDataFeed."""
    return MockDataFeed(**kwargs)


def make_strategy(
    datas: list[Any] | None = None,
    cash: float = 10000.0,
) -> Strategy:
    """Create a Strategy wired to a BackBroker and mock data.

    Returns a Strategy ready for use in tests.
    """
    broker = BackBroker(cash=cash)
    broker.start()

    if datas is None:
        datas = [make_data()]

    strat = Strategy()
    strat.setdatas(datas)
    strat.broker = broker
    strat._sizer.broker = broker

    return strat


# ---------------------------------------------------------------------------
# Strategy creation and defaults
# ---------------------------------------------------------------------------


class TestStrategyCreation:
    def test_default_construction(self):
        strat = Strategy()
        assert strat.datas == []
        assert strat.data is None
        assert strat.broker is None
        assert strat._orders == []
        assert strat._trades == {}
        assert strat._minperiod == 1

    def test_setdatas_single(self):
        strat = Strategy()
        data = make_data(name="AAPL")
        strat.setdatas([data])
        assert strat.data is data
        assert strat.datas == [data]
        assert strat.data0 is data
        assert strat.dnames == {"AAPL": data}

    def test_setdatas_multiple(self):
        strat = Strategy()
        d0 = make_data(name="AAPL")
        d1 = make_data(name="GOOG")
        strat.setdatas([d0, d1])
        assert strat.data is d0
        assert strat.data0 is d0
        assert strat.data1 is d1
        assert strat.dnames["AAPL"] is d0
        assert strat.dnames["GOOG"] is d1

    def test_default_sizer_is_fixed_size(self):
        strat = Strategy()
        assert isinstance(strat.getsizer(), FixedSize)

    def test_setsizer(self):
        strat = make_strategy()
        new_sizer = PercentSizer(percents=50)
        strat.setsizer(new_sizer)
        assert strat.getsizer() is new_sizer
        assert new_sizer.strategy is strat
        assert new_sizer.broker is strat.broker


# ---------------------------------------------------------------------------
# Strategy with params
# ---------------------------------------------------------------------------


class TestStrategyParams:
    def test_params_access(self):
        class MyStrat(Strategy):
            params = (("period", 20), ("multiplier", 2.0))

        strat = MyStrat()
        assert strat.p.period == 20
        assert strat.p.multiplier == 2.0

    def test_no_params(self):
        strat = Strategy()
        with pytest.raises(AttributeError):
            _ = strat.p.nonexistent


# ---------------------------------------------------------------------------
# Lifecycle hooks
# ---------------------------------------------------------------------------


class TestLifecycle:
    def test_start_called(self):
        calls = []

        class MyStrat(Strategy):
            def start(self):
                calls.append("start")

        strat = MyStrat()
        strat.start()
        assert calls == ["start"]

    def test_stop_called(self):
        calls = []

        class MyStrat(Strategy):
            def stop(self):
                calls.append("stop")

        strat = MyStrat()
        strat.stop()
        assert calls == ["stop"]

    def test_prenext_during_warmup(self):
        calls = []

        class MyStrat(Strategy):
            def prenext(self):
                calls.append("prenext")

            def next(self):
                calls.append("next")

        strat = MyStrat()
        strat._minperiod = 3

        # Bars 1 and 2 are during warmup.
        strat._onbar(1)
        strat._onbar(2)

        assert calls == ["prenext", "prenext"]

    def test_nextstart_called_once(self):
        calls = []

        class MyStrat(Strategy):
            def prenext(self):
                calls.append("prenext")

            def nextstart(self):
                calls.append("nextstart")

            def next(self):
                calls.append("next")

        strat = MyStrat()
        strat._minperiod = 3

        strat._onbar(1)  # prenext
        strat._onbar(2)  # prenext
        strat._onbar(3)  # nextstart (first valid bar)
        strat._onbar(4)  # next
        strat._onbar(5)  # next

        assert calls == ["prenext", "prenext", "nextstart", "next", "next"]

    def test_nextstart_default_calls_next(self):
        calls = []

        class MyStrat(Strategy):
            def next(self):
                calls.append("next")

        strat = MyStrat()
        strat._minperiod = 2

        strat._onbar(1)  # prenext (no override, does nothing)
        strat._onbar(2)  # nextstart -> next (default)
        strat._onbar(3)  # next

        assert calls == ["next", "next"]

    def test_next_open(self):
        calls = []

        class MyStrat(Strategy):
            def next_open(self):
                calls.append("next_open")

        strat = MyStrat()
        strat.next_open()
        assert calls == ["next_open"]

    def test_full_lifecycle_sequence(self):
        calls = []

        class MyStrat(Strategy):
            def start(self):
                calls.append("start")

            def prenext(self):
                calls.append("prenext")

            def nextstart(self):
                calls.append("nextstart")

            def next(self):
                calls.append("next")

            def stop(self):
                calls.append("stop")

        strat = MyStrat()
        strat._minperiod = 2

        strat.start()
        strat._onbar(1)  # prenext
        strat._onbar(2)  # nextstart
        strat._onbar(3)  # next
        strat.stop()

        assert calls == ["start", "prenext", "nextstart", "next", "stop"]


# ---------------------------------------------------------------------------
# Order API
# ---------------------------------------------------------------------------


class TestOrderAPI:
    def test_buy_default(self):
        strat = make_strategy()
        order = strat.buy()

        assert order is not None
        assert order.size > 0  # Buy order has positive size.
        assert order.data is strat.data
        assert order in strat._orders

    def test_sell_default(self):
        strat = make_strategy()
        order = strat.sell()

        assert order is not None
        assert order.size < 0  # Sell order has negative size.
        assert order.data is strat.data
        assert order in strat._orders

    def test_buy_explicit_size(self):
        strat = make_strategy()
        order = strat.buy(size=50)
        assert abs(order.size) == 50

    def test_sell_explicit_size(self):
        strat = make_strategy()
        order = strat.sell(size=30)
        assert abs(order.size) == 30

    def test_buy_with_data(self):
        d0 = make_data(name="AAPL")
        d1 = make_data(name="GOOG")
        strat = make_strategy(datas=[d0, d1])

        order = strat.buy(data=d1, size=10)
        assert order.data is d1

    def test_buy_with_limit(self):
        strat = make_strategy()
        order = strat.buy(
            size=10,
            price=100.0,
            exectype=ExecType.Limit,
        )
        assert order.exectype == ExecType.Limit
        assert order.price == 100.0

    def test_sell_with_stop(self):
        strat = make_strategy()
        order = strat.sell(
            size=5,
            price=95.0,
            exectype=ExecType.Stop,
        )
        assert order.exectype == ExecType.Stop
        assert order.price == 95.0

    def test_orders_tracked(self):
        strat = make_strategy()
        o1 = strat.buy(size=10)
        o2 = strat.sell(size=5)
        assert len(strat._orders) == 2
        assert o1 in strat._orders
        assert o2 in strat._orders


class TestCloseOrder:
    def test_close_long_position(self):
        strat = make_strategy()
        # Create a long position via buy + execute.
        strat.buy(size=10)
        strat.broker.next()  # Execute the buy.

        pos = strat.getposition()
        assert pos.size == 10

        order = strat.close()
        assert order is not None
        assert order.size < 0  # Sell to close long.

    def test_close_short_position(self):
        strat = make_strategy()
        # Create a short position.
        strat.sell(size=10)
        strat.broker.next()

        pos = strat.getposition()
        assert pos.size == -10

        order = strat.close()
        assert order is not None
        assert order.size > 0  # Buy to close short.

    def test_close_flat_returns_none(self):
        strat = make_strategy()
        order = strat.close()
        assert order is None


class TestCancel:
    def test_cancel_order(self):
        strat = make_strategy()
        order = strat.buy(
            size=10,
            price=50.0,
            exectype=ExecType.Limit,
        )
        assert order.alive

        strat.cancel(order)
        assert order.status == OrderStatus.Canceled


# ---------------------------------------------------------------------------
# Target-based orders
# ---------------------------------------------------------------------------


class TestTargetOrders:
    def test_order_target_size_from_flat(self):
        strat = make_strategy()
        order = strat.order_target_size(target=10)
        assert order is not None
        assert order.size > 0  # Should buy.

    def test_order_target_size_reduce(self):
        strat = make_strategy()
        strat.buy(size=20)
        strat.broker.next()

        order = strat.order_target_size(target=10)
        assert order is not None
        assert order.size < 0  # Should sell the difference.

    def test_order_target_size_already_at_target(self):
        strat = make_strategy()
        strat.buy(size=10)
        strat.broker.next()

        order = strat.order_target_size(target=10)
        assert order is None

    def test_order_target_size_go_short(self):
        strat = make_strategy()
        order = strat.order_target_size(target=-5)
        assert order is not None
        assert order.size < 0

    def test_order_target_value(self):
        # Price is 105 (from MockDataFeed close default).
        strat = make_strategy(cash=100000.0)

        # Target value of 1050 at price 105 -> 10 shares.
        order = strat.order_target_value(target=1050.0)
        assert order is not None
        assert order.size > 0

    def test_order_target_value_no_change(self):
        strat = make_strategy(cash=100000.0)
        strat.buy(size=10)
        strat.broker.next()

        # Current position: 10 shares at ~105. Value ~1050.
        order = strat.order_target_value(target=1050.0)
        # Should be None or very small since already at target.
        # The position price is the execution price (open=100), so pos.size*close=10*105=1050.
        # But position was at open price, so 10*105 is the target. Let's check.
        # Actually the target is checked against pos.size * provided_price.
        # Default price is close=105, so current_value=10*105=1050. diff=0. => None.
        assert order is None

    def test_order_target_percent(self):
        strat = make_strategy(cash=10000.0)

        # Target 10% of portfolio value.
        order = strat.order_target_percent(target=0.1)
        assert order is not None
        assert order.size > 0


# ---------------------------------------------------------------------------
# Bracket orders
# ---------------------------------------------------------------------------


class TestBracketOrders:
    def test_buy_bracket(self):
        strat = make_strategy()
        orders = strat.buy_bracket(
            size=10,
            price=100.0,
            stopprice=90.0,
            limitprice=120.0,
        )

        assert len(orders) == 3
        main, stop, limit = orders

        # Main order.
        assert main.size > 0
        assert main.transmit is False

        # Stop loss (sell stop).
        assert stop.size < 0
        assert stop.exectype == ExecType.Stop
        assert stop.price == 90.0
        assert stop.parent is main

        # Take profit (sell limit).
        assert limit.size < 0
        assert limit.exectype == ExecType.Limit
        assert limit.price == 120.0
        assert limit.parent is main

    def test_sell_bracket(self):
        strat = make_strategy()
        orders = strat.sell_bracket(
            size=10,
            price=100.0,
            stopprice=110.0,
            limitprice=80.0,
        )

        assert len(orders) == 3
        main, stop, limit = orders

        # Main order (sell).
        assert main.size < 0

        # Stop loss (buy stop above entry).
        assert stop.size > 0
        assert stop.exectype == ExecType.Stop
        assert stop.price == 110.0
        assert stop.parent is main

        # Take profit (buy limit below entry).
        assert limit.size > 0
        assert limit.exectype == ExecType.Limit
        assert limit.price == 80.0
        assert limit.parent is main

    def test_bracket_orders_tracked(self):
        strat = make_strategy()
        orders = strat.buy_bracket(
            size=10,
            price=100.0,
            stopprice=90.0,
            limitprice=120.0,
        )
        # All 3 orders should be in _orders.
        assert len(strat._orders) == 3
        for o in orders:
            assert o in strat._orders


# ---------------------------------------------------------------------------
# Notification system
# ---------------------------------------------------------------------------


class TestNotifications:
    def test_notify_order_default(self):
        """Default notify_order does nothing (no error)."""
        strat = Strategy()
        order = Order(size=10)
        strat.notify_order(order)  # Should not raise.

    def test_notify_order_override(self):
        notifications = []

        class MyStrat(Strategy):
            def notify_order(self, order):
                notifications.append(order)

        strat = MyStrat()
        order = Order(size=10)
        strat.notify_order(order)
        assert len(notifications) == 1
        assert notifications[0] is order

    def test_notify_trade_default(self):
        strat = Strategy()
        trade = SimpleNamespace(pnl=100.0)
        strat.notify_trade(trade)  # Should not raise.

    def test_notify_trade_override(self):
        notifications = []

        class MyStrat(Strategy):
            def notify_trade(self, trade):
                notifications.append(trade)

        strat = MyStrat()
        trade = SimpleNamespace(pnl=100.0)
        strat.notify_trade(trade)
        assert notifications == [trade]

    def test_notify_cashvalue(self):
        notifications = []

        class MyStrat(Strategy):
            def notify_cashvalue(self, cash, value):
                notifications.append((cash, value))

        strat = MyStrat()
        strat.notify_cashvalue(5000.0, 10000.0)
        assert notifications == [(5000.0, 10000.0)]

    def test_notify_fund(self):
        notifications = []

        class MyStrat(Strategy):
            def notify_fund(self, cash, value, fundvalue, shares):
                notifications.append((cash, value, fundvalue, shares))

        strat = MyStrat()
        strat.notify_fund(5000.0, 10000.0, 100.0, 100.0)
        assert notifications == [(5000.0, 10000.0, 100.0, 100.0)]

    def test_notify_store(self):
        notifications = []

        class MyStrat(Strategy):
            def notify_store(self, msg, *args, **kwargs):
                notifications.append(msg)

        strat = MyStrat()
        strat.notify_store("connected")
        assert notifications == ["connected"]

    def test_notify_data(self):
        notifications = []

        class MyStrat(Strategy):
            def notify_data(self, data, status, *args, **kwargs):
                notifications.append((data, status))

        strat = MyStrat()
        strat.notify_data("feed1", "LIVE")
        assert notifications == [("feed1", "LIVE")]

    def test_notify_timer(self):
        notifications = []

        class MyStrat(Strategy):
            def notify_timer(self, timer, when, *args, **kwargs):
                notifications.append((timer, when))

        strat = MyStrat()
        strat.notify_timer("daily", "09:30")
        assert notifications == [("daily", "09:30")]


# ---------------------------------------------------------------------------
# Position access
# ---------------------------------------------------------------------------


class TestPositionAccess:
    def test_getposition_default_data(self):
        strat = make_strategy()
        pos = strat.getposition()
        assert isinstance(pos, Position)
        assert pos.size == 0

    def test_getposition_specific_data(self):
        d0 = make_data(name="AAPL")
        d1 = make_data(name="GOOG")
        strat = make_strategy(datas=[d0, d1])

        pos0 = strat.getposition(d0)
        pos1 = strat.getposition(d1)
        assert pos0.size == 0
        assert pos1.size == 0

    def test_position_property(self):
        strat = make_strategy()
        pos = strat.position
        assert isinstance(pos, Position)
        assert pos.size == 0

    def test_position_after_buy(self):
        strat = make_strategy()
        strat.buy(size=10)
        strat.broker.next()

        assert strat.position.size == 10

    def test_position_after_sell(self):
        strat = make_strategy()
        strat.sell(size=5)
        strat.broker.next()

        assert strat.position.size == -5


# ---------------------------------------------------------------------------
# Sizer integration
# ---------------------------------------------------------------------------


class TestSizerIntegration:
    def test_default_sizer_fixed_one(self):
        strat = make_strategy()
        order = strat.buy()
        # Default FixedSize has stake=1.
        assert abs(order.size) == 1

    def test_custom_fixed_sizer(self):
        strat = make_strategy()
        strat.setsizer(FixedSize(stake=25))

        order = strat.buy()
        assert abs(order.size) == 25

    def test_explicit_size_overrides_sizer(self):
        strat = make_strategy()
        strat.setsizer(FixedSize(stake=100))

        order = strat.buy(size=5)
        assert abs(order.size) == 5

    def test_percent_sizer(self):
        strat = make_strategy(cash=10000.0)
        sizer = PercentSizer(percents=50)
        strat.setsizer(sizer)

        order = strat.buy()
        # 50% of 10000 = 5000 cash, at close price 105 -> int(5000/105) = 47
        assert abs(order.size) == 47


# ---------------------------------------------------------------------------
# Environment access
# ---------------------------------------------------------------------------


class TestEnvironmentAccess:
    def test_env_and_cortex_alias(self):
        strat = Strategy()
        env = SimpleNamespace(name="cortex")
        strat.env = env
        assert strat.cortex is env
        assert strat.env is env

    def test_cortex_setter(self):
        strat = Strategy()
        env = SimpleNamespace(name="cortex")
        strat.cortex = env
        assert strat.env is env

    def test_broker_access(self):
        strat = make_strategy()
        assert strat.broker is not None
        assert isinstance(strat.broker, BackBroker)

    def test_orders_list(self):
        strat = make_strategy()
        assert strat._orders == []
        strat.buy(size=1)
        assert len(strat._orders) == 1

    def test_trades_dict(self):
        strat = make_strategy()
        assert strat._trades == {}

    def test_stats_and_analyzers(self):
        strat = Strategy()
        assert strat.stats == []
        assert strat.analyzers == []


# ---------------------------------------------------------------------------
# Writer support
# ---------------------------------------------------------------------------


class TestWriterSupport:
    def test_getwriterheaders(self):
        data = make_data(name="AAPL")
        strat = make_strategy(datas=[data])

        headers = strat.getwriterheaders()
        assert "AAPL.close" in headers
        assert "AAPL.open" in headers

    def test_getwritervalues(self):
        data = make_data(close=105.0, open=100.0)
        strat = make_strategy(datas=[data])

        values = strat.getwritervalues()
        assert 105.0 in values
        assert 100.0 in values

    def test_writer_multiple_data(self):
        d0 = make_data(name="AAPL", close=150.0)
        d1 = make_data(name="GOOG", close=2800.0)
        strat = make_strategy(datas=[d0, d1])

        headers = strat.getwriterheaders()
        assert "AAPL.close" in headers
        assert "GOOG.close" in headers

        values = strat.getwritervalues()
        assert 150.0 in values
        assert 2800.0 in values


# ---------------------------------------------------------------------------
# Indicator registration
# ---------------------------------------------------------------------------


class TestIndicatorRegistration:
    def test_addindicator_updates_minperiod(self):
        strat = Strategy()
        indicator = SimpleNamespace(_minperiod=10)
        strat.addindicator(indicator)

        assert strat._minperiod == 10
        assert indicator in strat._lineiterators[0]

    def test_addindicator_takes_max_period(self):
        strat = Strategy()
        ind1 = SimpleNamespace(_minperiod=5)
        ind2 = SimpleNamespace(_minperiod=20)
        ind3 = SimpleNamespace(_minperiod=10)

        strat.addindicator(ind1)
        strat.addindicator(ind2)
        strat.addindicator(ind3)

        assert strat._minperiod == 20

    def test_addobserver(self):
        strat = Strategy()
        obs = SimpleNamespace(name="observer")
        strat.addobserver(obs)
        assert obs in strat._lineiterators[2]


# ---------------------------------------------------------------------------
# Integration: strategy with broker round-trip
# ---------------------------------------------------------------------------


class TestStrategyBrokerIntegration:
    def test_buy_and_execute(self):
        strat = make_strategy()
        order = strat.buy(size=10)
        strat.broker.next()

        assert strat.position.size == 10
        assert order.status == OrderStatus.Completed

    def test_buy_then_sell_to_close(self):
        strat = make_strategy()
        strat.buy(size=10)
        strat.broker.next()

        strat.sell(size=10)
        strat.broker.next()

        assert strat.position.size == 0

    def test_multiple_orders_tracking(self):
        strat = make_strategy()
        strat.buy(size=5)
        strat.buy(size=3)
        assert len(strat._orders) == 2

        strat.broker.next()
        assert strat.position.size == 8

    def test_lifecycle_with_broker(self):
        """Simulate a minimal backtest loop."""
        calls = []

        class TestStrat(Strategy):
            def start(self):
                calls.append("start")

            def prenext(self):
                calls.append("prenext")

            def nextstart(self):
                calls.append("nextstart")

            def next(self):
                calls.append("next")
                if len(calls) == 4:  # On first next after nextstart
                    self.buy(size=1)

            def stop(self):
                calls.append("stop")

        broker = BackBroker(cash=10000.0)
        broker.start()
        data = make_data()

        strat = TestStrat()
        strat.setdatas([data])
        strat.broker = broker
        strat._sizer.broker = broker
        strat._minperiod = 2

        strat.start()
        strat._onbar(1)  # prenext
        strat._onbar(2)  # nextstart
        strat._onbar(3)  # next (places buy)
        broker.next()     # Execute the buy
        strat.stop()

        assert calls == ["start", "prenext", "nextstart", "next", "stop"]
        assert strat.position.size == 1
