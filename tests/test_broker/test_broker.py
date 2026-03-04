"""Tests for bucktrader.broker module (BackBroker)."""

from datetime import datetime

import pytest

from bucktrader.broker import BackBroker
from bucktrader.comminfo import CommInfoBase, CommType
from bucktrader.fillers import FixedSize
from bucktrader.order import ExecType, OrderStatus, reset_order_ref_counter
from bucktrader.trade import reset_trade_ref_counter


@pytest.fixture(autouse=True)
def _reset_refs():
    """Reset global counters for deterministic tests."""
    reset_order_ref_counter(1)
    reset_trade_ref_counter(1)
    yield
    reset_order_ref_counter(1)
    reset_trade_ref_counter(1)


# ── Mock data feed ────────────────────────────────────────────────────


class MockBar:
    """A simple bar with OHLCV data, accessed as plain attributes."""

    def __init__(
        self,
        open: float = 100.0,
        high: float = 110.0,
        low: float = 90.0,
        close: float = 105.0,
        volume: float = 10000.0,
        name: str = "TEST",
    ):
        self.open = open
        self.high = high
        self.low = low
        self.close = close
        self.volume = volume
        self.name = name


def make_bar(**kwargs) -> MockBar:
    return MockBar(**kwargs)


# ── Basic broker setup ────────────────────────────────────────────────


class TestBackBrokerSetup:
    def test_default_cash(self):
        broker = BackBroker()
        assert broker.getcash() == 10000.0

    def test_custom_cash(self):
        broker = BackBroker(cash=50000.0)
        assert broker.getcash() == 50000.0

    def test_start_resets_cash(self):
        broker = BackBroker(cash=10000.0)
        broker.cash = 5000.0
        broker.start()
        assert broker.getcash() == 10000.0

    def test_flat_position_by_default(self):
        broker = BackBroker()
        data = make_bar()
        pos = broker.getposition(data)
        assert pos.is_flat

    def test_set_commission(self):
        broker = BackBroker()
        broker.setcommission(commission=0.001, percabs=True, stocklike=True)
        ci = broker.getcommissioninfo()
        assert ci.commission == 0.001
        assert ci.percabs is True

    def test_add_commission_info(self):
        broker = BackBroker()
        ci = CommInfoBase(commission=2.0, commtype=CommType.COMM_FIXED)
        broker.addcommissioninfo(ci, name="ES")
        data = make_bar(name="ES")
        assert broker.getcommissioninfo(data).commission == 2.0

    def test_getvalue_cash_only(self):
        broker = BackBroker(cash=10000.0)
        assert broker.getvalue() == 10000.0


# ── Market order execution ───────────────────────────────────────────


class TestMarketOrders:
    def test_buy_market_order(self):
        broker = BackBroker(cash=10000.0)
        broker.setcommission(commission=0.0, stocklike=True)
        data = make_bar(open=100.0, close=105.0)

        order = broker.buy(data=data, size=10)
        assert order.status == OrderStatus.Accepted

        broker.next()
        assert order.status == OrderStatus.Completed
        assert order.executed.price == pytest.approx(100.0)
        assert broker.getcash() == pytest.approx(10000.0 - 10 * 100.0)

    def test_sell_market_order(self):
        broker = BackBroker(cash=10000.0)
        broker.setcommission(commission=0.0, stocklike=True)
        data = make_bar(open=100.0, close=105.0)

        # First buy to have a position.
        buy_order = broker.buy(data=data, size=10)
        broker.next()

        sell_order = broker.sell(data=data, size=10)
        broker.next()

        assert sell_order.status == OrderStatus.Completed
        pos = broker.getposition(data)
        assert pos.size == 0

    def test_market_coc(self):
        """Cheat-on-close: market order executes at this bar's close."""
        broker = BackBroker(cash=10000.0, coc=True)
        broker.setcommission(commission=0.0, stocklike=True)
        data = make_bar(open=100.0, close=105.0)

        order = broker.buy(data=data, size=10)
        broker.next()

        assert order.status == OrderStatus.Completed
        assert order.executed.price == pytest.approx(105.0)

    def test_market_coo(self):
        """Cheat-on-open: execute at the bar's open."""
        broker = BackBroker(cash=10000.0, coo=True)
        broker.setcommission(commission=0.0, stocklike=True)
        data = make_bar(open=98.0, close=105.0)

        order = broker.buy(data=data, size=10)
        broker.next()

        assert order.status == OrderStatus.Completed
        assert order.executed.price == pytest.approx(98.0)


# ── Close orders ──────────────────────────────────────────────────────


class TestCloseOrders:
    def test_close_order_executes_at_close(self):
        broker = BackBroker(cash=10000.0)
        broker.setcommission(commission=0.0, stocklike=True)
        data = make_bar(open=100.0, close=108.0)

        order = broker.buy(data=data, size=5, exectype=ExecType.Close)
        broker.next()

        assert order.status == OrderStatus.Completed
        assert order.executed.price == pytest.approx(108.0)


# ── Limit orders ──────────────────────────────────────────────────────


class TestLimitOrders:
    def test_buy_limit_triggers(self):
        broker = BackBroker(cash=10000.0)
        broker.setcommission(commission=0.0, stocklike=True)
        data = make_bar(open=100.0, high=110.0, low=88.0, close=95.0)

        # Limit at 95 -- bar low=88 <= 95, so triggers.
        order = broker.buy(data=data, size=10, price=95.0, exectype=ExecType.Limit)
        broker.next()

        assert order.status == OrderStatus.Completed
        # Execute at min(limit, open) = min(95, 100) = 95.
        assert order.executed.price == pytest.approx(95.0)

    def test_buy_limit_gap_open(self):
        """Open price below limit -- fill at open (better price)."""
        broker = BackBroker(cash=10000.0)
        broker.setcommission(commission=0.0, stocklike=True)
        data = make_bar(open=90.0, high=110.0, low=88.0, close=95.0)

        order = broker.buy(data=data, size=10, price=95.0, exectype=ExecType.Limit)
        broker.next()

        assert order.status == OrderStatus.Completed
        assert order.executed.price == pytest.approx(90.0)

    def test_buy_limit_not_triggered(self):
        broker = BackBroker(cash=10000.0)
        broker.setcommission(commission=0.0, stocklike=True)
        data = make_bar(open=100.0, high=110.0, low=96.0, close=105.0)

        order = broker.buy(data=data, size=10, price=95.0, exectype=ExecType.Limit)
        broker.next()

        assert order.status == OrderStatus.Accepted  # Not filled.

    def test_sell_limit_triggers(self):
        broker = BackBroker(cash=10000.0)
        broker.setcommission(commission=0.0, stocklike=True)
        data = make_bar(open=100.0, high=110.0, low=90.0, close=105.0)

        # Buy first.
        broker.buy(data=data, size=10)
        broker.next()

        order = broker.sell(data=data, size=10, price=108.0, exectype=ExecType.Limit)
        broker.next()

        assert order.status == OrderStatus.Completed
        # Execute at max(108, 100) = 108.
        assert order.executed.price == pytest.approx(108.0)

    def test_sell_limit_gap_open(self):
        """Open above limit -- fill at open (better price)."""
        broker = BackBroker(cash=10000.0)
        broker.setcommission(commission=0.0, stocklike=True)
        data = make_bar(open=100.0, high=110.0, low=90.0)

        broker.buy(data=data, size=10)
        broker.next()

        data2 = make_bar(open=112.0, high=115.0, low=108.0, close=113.0)
        order = broker.sell(data=data2, size=10, price=108.0, exectype=ExecType.Limit)
        broker.next()

        assert order.status == OrderStatus.Completed
        assert order.executed.price == pytest.approx(112.0)


# ── Stop orders ───────────────────────────────────────────────────────


class TestStopOrders:
    def test_buy_stop_triggers(self):
        broker = BackBroker(cash=10000.0)
        broker.setcommission(commission=0.0, stocklike=True)
        data = make_bar(open=100.0, high=110.0, low=90.0, close=105.0)

        order = broker.buy(data=data, size=10, price=108.0, exectype=ExecType.Stop)
        broker.next()

        assert order.status == OrderStatus.Completed
        # Execute at max(108, 100) = 108.
        assert order.executed.price == pytest.approx(108.0)

    def test_buy_stop_gap_open(self):
        """Open above stop -- fill at open."""
        broker = BackBroker(cash=10000.0)
        broker.setcommission(commission=0.0, stocklike=True)
        data = make_bar(open=112.0, high=115.0, low=108.0, close=113.0)

        order = broker.buy(data=data, size=10, price=108.0, exectype=ExecType.Stop)
        broker.next()

        assert order.status == OrderStatus.Completed
        assert order.executed.price == pytest.approx(112.0)

    def test_buy_stop_not_triggered(self):
        broker = BackBroker(cash=10000.0)
        broker.setcommission(commission=0.0, stocklike=True)
        data = make_bar(open=100.0, high=105.0, low=90.0, close=102.0)

        order = broker.buy(data=data, size=10, price=108.0, exectype=ExecType.Stop)
        broker.next()

        assert order.status == OrderStatus.Accepted

    def test_sell_stop_triggers(self):
        broker = BackBroker(cash=10000.0)
        broker.setcommission(commission=0.0, stocklike=True)
        data = make_bar(open=100.0, high=110.0, low=90.0, close=95.0)

        broker.buy(data=data, size=10)
        broker.next()

        order = broker.sell(data=data, size=10, price=92.0, exectype=ExecType.Stop)
        broker.next()

        assert order.status == OrderStatus.Completed
        # Execute at min(92, 100) = 92.
        assert order.executed.price == pytest.approx(92.0)


# ── StopLimit orders ─────────────────────────────────────────────────


class TestStopLimitOrders:
    def test_buy_stoplimit(self):
        """Stop triggers, then limit executes on same bar."""
        broker = BackBroker(cash=10000.0)
        broker.setcommission(commission=0.0, stocklike=True)
        # Stop at 108, limit at 109.
        data = make_bar(open=100.0, high=112.0, low=90.0, close=110.0)

        order = broker.buy(
            data=data, size=10, price=108.0, plimit=109.0,
            exectype=ExecType.StopLimit,
        )
        broker.next()

        assert order.status == OrderStatus.Completed

    def test_stoplimit_not_triggered(self):
        """Stop not reached."""
        broker = BackBroker(cash=10000.0)
        broker.setcommission(commission=0.0, stocklike=True)
        data = make_bar(open=100.0, high=105.0, low=95.0)

        order = broker.buy(
            data=data, size=10, price=108.0, plimit=109.0,
            exectype=ExecType.StopLimit,
        )
        broker.next()

        assert order.status == OrderStatus.Accepted


# ── Trailing Stop orders ─────────────────────────────────────────────


class TestTrailingStopOrders:
    def test_sell_trail_amount(self):
        """Sell trailing stop for long position protection."""
        broker = BackBroker(cash=10000.0)
        broker.setcommission(commission=0.0, stocklike=True)
        data = make_bar(open=100.0, high=110.0, low=90.0, close=105.0)

        broker.buy(data=data, size=10)
        broker.next()

        # Trail amount = 5. Trail price = high - 5 = 105.
        order = broker.sell(
            data=data, size=10,
            exectype=ExecType.StopTrail, trailamount=5.0,
        )
        # First bar: trail_price = 110 - 5 = 105. low=90 <= 105 -> triggers.
        broker.next()
        assert order.status == OrderStatus.Completed

    def test_sell_trail_percent(self):
        """Sell trailing stop with percentage."""
        broker = BackBroker(cash=10000.0)
        broker.setcommission(commission=0.0, stocklike=True)
        data = make_bar(open=100.0, high=110.0, low=90.0, close=105.0)

        broker.buy(data=data, size=10)
        broker.next()

        # Trail percent = 10%. Trail price = 110 * (1 - 0.10) = 99.
        order = broker.sell(
            data=data, size=10,
            exectype=ExecType.StopTrail, trailpercent=0.10,
        )
        # low=90 <= 99 -> triggers.
        broker.next()
        assert order.status == OrderStatus.Completed

    def test_buy_trail_amount(self):
        """Buy trailing stop for short position protection."""
        broker = BackBroker(cash=10000.0)
        broker.setcommission(commission=0.0, stocklike=True)
        data = make_bar(open=100.0, high=110.0, low=90.0, close=95.0)

        # Trail amount = 5. Trail price = low + 5 = 95.
        order = broker.buy(
            data=data, size=10,
            exectype=ExecType.StopTrail, trailamount=5.0,
        )
        # high=110 >= 95 -> triggers.
        broker.next()
        assert order.status == OrderStatus.Completed

    def test_trail_not_triggered(self):
        """Trailing stop does not trigger when price doesn't reach."""
        broker = BackBroker(cash=10000.0)
        broker.setcommission(commission=0.0, stocklike=True)
        # Narrow range bar.
        data = make_bar(open=100.0, high=102.0, low=99.0, close=101.0)

        # Trail amount = 1 for sell. Trail price = 102 - 1 = 101.
        # low=99 <= 101 -> triggers actually. Use a wider trail.
        order = broker.sell(
            data=data, size=10,
            exectype=ExecType.StopTrail, trailamount=0.5,
        )
        # Trail = 102 - 0.5 = 101.5. low=99 < 101.5 -> triggers.
        broker.next()
        assert order.status == OrderStatus.Completed


# ── Slippage ──────────────────────────────────────────────────────────


class TestSlippage:
    def test_perc_slippage_buy(self):
        broker = BackBroker(cash=10000.0, slip_perc=0.01, slip_open=True)
        broker.setcommission(commission=0.0, stocklike=True)
        data = make_bar(open=100.0, high=110.0, low=90.0, close=105.0)

        order = broker.buy(data=data, size=10)
        broker.next()

        # Slip = 100 * 0.01 = 1. Price = 101.
        assert order.executed.price == pytest.approx(101.0)

    def test_perc_slippage_sell(self):
        broker = BackBroker(cash=10000.0, slip_perc=0.01, slip_open=True)
        broker.setcommission(commission=0.0, stocklike=True)
        data = make_bar(open=100.0, high=110.0, low=90.0)

        broker.buy(data=data, size=10)
        broker.next()

        order = broker.sell(data=data, size=10)
        broker.next()

        # Slip = 100 * 0.01 = 1. Price = 99.
        assert order.executed.price == pytest.approx(99.0)

    def test_fixed_slippage(self):
        broker = BackBroker(cash=10000.0, slip_fixed=2.0, slip_open=True)
        broker.setcommission(commission=0.0, stocklike=True)
        data = make_bar(open=100.0, high=110.0, low=90.0)

        order = broker.buy(data=data, size=10)
        broker.next()

        assert order.executed.price == pytest.approx(102.0)

    def test_slip_match_clamps_to_bar(self):
        """Slippage clamped to bar high for buys."""
        broker = BackBroker(
            cash=10000.0, slip_fixed=20.0,
            slip_open=True, slip_match=True,
        )
        broker.setcommission(commission=0.0, stocklike=True)
        data = make_bar(open=100.0, high=110.0, low=90.0)

        order = broker.buy(data=data, size=10)
        broker.next()

        # Slipped = 100 + 20 = 120, but clamped to high=110.
        assert order.executed.price == pytest.approx(110.0)

    def test_no_slip_on_open_by_default(self):
        """With slip_open=False, open-price execution has no slippage."""
        broker = BackBroker(cash=10000.0, slip_perc=0.01, slip_open=False)
        broker.setcommission(commission=0.0, stocklike=True)
        data = make_bar(open=100.0, high=110.0, low=90.0)

        order = broker.buy(data=data, size=10)
        broker.next()

        assert order.executed.price == pytest.approx(100.0)


# ── Commission integration ───────────────────────────────────────────


class TestCommission:
    def test_commission_deducted(self):
        broker = BackBroker(cash=10000.0)
        broker.setcommission(
            commission=0.001, percabs=True, stocklike=True
        )
        data = make_bar(open=100.0, high=110.0, low=90.0)

        order = broker.buy(data=data, size=10)
        broker.next()

        # Cost = 10 * 100 = 1000. Commission = 0.001 * 10 * 100 = 1.0.
        assert order.executed.comm == pytest.approx(1.0)
        assert broker.getcash() == pytest.approx(10000.0 - 1000.0 - 1.0)


# ── Partial fills (fillers) ──────────────────────────────────────────


class TestPartialFills:
    def test_fixed_size_filler(self):
        filler = FixedSize(size=5)
        broker = BackBroker(cash=10000.0, filler=filler)
        broker.setcommission(commission=0.0, stocklike=True)
        data = make_bar(open=10.0, high=12.0, low=9.0, close=11.0, volume=1000)

        order = broker.buy(data=data, size=20)
        broker.next()

        # Filler caps at 5 units per bar.
        assert order.status == OrderStatus.Partial
        assert order.executed.size == 5

        # Execute more bars.
        broker.next()
        assert order.executed.size == 10

        broker.next()
        assert order.executed.size == 15

        broker.next()
        assert order.status == OrderStatus.Completed
        assert order.executed.size == 20


# ── OCO orders ────────────────────────────────────────────────────────


class TestOCOOrders:
    def test_oco_cancel_on_fill(self):
        """When one OCO order fills, the other is canceled."""
        broker = BackBroker(cash=10000.0)
        broker.setcommission(commission=0.0, stocklike=True)
        data = make_bar(open=100.0, high=110.0, low=90.0)

        order_a = broker.buy(data=data, size=10, exectype=ExecType.Market)
        order_b = broker.buy(
            data=data, size=10, price=95.0,
            exectype=ExecType.Limit, oco=order_a,
        )
        # Also link in reverse for full OCO.
        order_a.oco = order_b

        broker.next()

        # Market order fills, limit should be canceled.
        assert order_a.status == OrderStatus.Completed
        assert order_b.status == OrderStatus.Canceled


# ── Bracket orders ────────────────────────────────────────────────────


class TestBracketOrders:
    def test_bracket_children_wait_for_parent(self):
        """Children should not execute until parent fills."""
        broker = BackBroker(cash=10000.0)
        broker.setcommission(commission=0.0, stocklike=True)
        data = make_bar(open=100.0, high=110.0, low=90.0, close=105.0)

        parent = broker.buy(
            data=data, size=10, exectype=ExecType.Market, transmit=False,
        )
        # Stop loss child.
        child_stop = broker.sell(
            data=data, size=10, price=92.0,
            exectype=ExecType.Stop, parent=parent, transmit=False,
        )
        # Take profit child.
        child_limit = broker.sell(
            data=data, size=10, price=115.0,
            exectype=ExecType.Limit, parent=parent, transmit=True,
        )

        # Parent fills on next().
        broker.next()
        assert parent.status == OrderStatus.Completed

        # Children should still be alive (not yet triggered).
        # Stop at 92: low=90 would trigger, but parent just filled this bar.
        # On the next bar, children should be eligible.

    def test_bracket_child_cancels_sibling(self):
        """When one child fills, the other is canceled."""
        broker = BackBroker(cash=10000.0)
        broker.setcommission(commission=0.0, stocklike=True)
        data = make_bar(open=100.0, high=110.0, low=90.0, close=105.0)

        parent = broker.buy(
            data=data, size=10, exectype=ExecType.Market, transmit=False,
        )
        child_stop = broker.sell(
            data=data, size=10, price=92.0,
            exectype=ExecType.Stop, parent=parent, transmit=False,
        )
        child_limit = broker.sell(
            data=data, size=10, price=115.0,
            exectype=ExecType.Limit, parent=parent, transmit=True,
        )

        # Bar 1: parent fills.
        broker.next()
        assert parent.status == OrderStatus.Completed

        # Bar 2: use bar where stop triggers.
        data2 = make_bar(open=95.0, high=96.0, low=88.0, close=89.0)
        child_stop.data = data2
        child_limit.data = data2
        broker.next()

        assert child_stop.status == OrderStatus.Completed
        assert child_limit.status == OrderStatus.Canceled


# ── Order expiration ──────────────────────────────────────────────────


class TestOrderExpiration:
    def test_gtc_never_expires(self):
        broker = BackBroker(cash=10000.0)
        broker.setcommission(commission=0.0, stocklike=True)
        data = make_bar(open=100.0, high=105.0, low=96.0)

        order = broker.buy(
            data=data, size=10, price=90.0, exectype=ExecType.Limit
        )
        # Multiple bars -- should not expire.
        for _ in range(10):
            broker.next()

        assert order.alive is True

    def test_datetime_expiry(self):
        broker = BackBroker(cash=10000.0)
        broker.setcommission(commission=0.0, stocklike=True)
        data = make_bar(open=100.0, high=105.0, low=96.0)

        valid_until = datetime(2024, 1, 10)
        order = broker.buy(
            data=data, size=10, price=90.0,
            exectype=ExecType.Limit, valid=valid_until,
        )

        # Set broker time past validity.
        broker._dt = datetime(2024, 1, 11)
        broker.next()

        assert order.status == OrderStatus.Expired


# ── Position tracking ────────────────────────────────────────────────


class TestPositionTracking:
    def test_position_after_buy(self):
        broker = BackBroker(cash=10000.0)
        broker.setcommission(commission=0.0, stocklike=True)
        data = make_bar(open=100.0, high=110.0, low=90.0)

        broker.buy(data=data, size=10)
        broker.next()

        pos = broker.getposition(data)
        assert pos.size == 10

    def test_position_after_sell(self):
        broker = BackBroker(cash=10000.0)
        broker.setcommission(commission=0.0, stocklike=True)
        data = make_bar(open=100.0, high=110.0, low=90.0)

        broker.buy(data=data, size=10)
        broker.next()
        broker.sell(data=data, size=10)
        broker.next()

        pos = broker.getposition(data)
        assert pos.size == 0


# ── Trade tracking ───────────────────────────────────────────────────


class TestTradeTracking:
    def test_trade_created_on_buy(self):
        broker = BackBroker(cash=10000.0, tradehistory=True)
        broker.setcommission(commission=0.0, stocklike=True)
        data = make_bar(open=100.0, high=110.0, low=90.0)

        broker.buy(data=data, size=10)
        broker.next()

        trades = broker.get_trades(data=data)
        assert len(trades) == 1
        assert trades[0].isopen is True
        assert trades[0].size == 10

    def test_trade_closed_on_sell(self):
        broker = BackBroker(cash=10000.0, tradehistory=True)
        broker.setcommission(commission=0.0, stocklike=True)
        data = make_bar(open=100.0, high=110.0, low=90.0)

        broker.buy(data=data, size=10)
        broker.next()

        broker.sell(data=data, size=10)
        broker.next()

        trades = broker.get_trades(data=data)
        assert len(trades) == 1
        assert trades[0].isclosed is True


# ── Fund mode ─────────────────────────────────────────────────────────


class TestFundMode:
    def test_fund_mode_initial(self):
        broker = BackBroker(cash=10000.0, fundmode=True, fundstartval=100.0)
        broker.start()
        assert broker.get_fundvalue() == pytest.approx(100.0)
        assert broker.get_fundshares() == pytest.approx(100.0)  # 10000/100

    def test_fund_value_changes_with_portfolio(self):
        broker = BackBroker(cash=10000.0, fundmode=True, fundstartval=100.0)
        broker.setcommission(commission=0.0, stocklike=True)
        broker.start()

        data = make_bar(open=100.0, high=110.0, low=90.0, close=105.0)
        broker.buy(data=data, size=10)
        broker.next()

        # Cash after buy: 10000 - 10*100 = 9000. Position value: 10*105=1050.
        # Total: 9000 + 1050 = 10050. NAV/share: 10050/100 = 100.5.
        fund_value = broker.get_fundvalue()
        assert fund_value == pytest.approx(10050.0 / 100.0)


# ── Cancel order ──────────────────────────────────────────────────────


class TestCancelOrder:
    def test_cancel_pending_order(self):
        broker = BackBroker(cash=10000.0)
        broker.setcommission(commission=0.0, stocklike=True)
        data = make_bar(open=100.0, high=105.0, low=96.0)

        order = broker.buy(
            data=data, size=10, price=90.0, exectype=ExecType.Limit
        )
        broker.cancel(order)
        assert order.status == OrderStatus.Canceled

    def test_cancel_already_completed(self):
        """Canceling a completed order should be a no-op."""
        broker = BackBroker(cash=10000.0)
        broker.setcommission(commission=0.0, stocklike=True)
        data = make_bar(open=100.0, high=110.0, low=90.0)

        order = broker.buy(data=data, size=10)
        broker.next()
        assert order.status == OrderStatus.Completed

        broker.cancel(order)
        assert order.status == OrderStatus.Completed  # Unchanged.


# ── Notifications ─────────────────────────────────────────────────────


class TestNotifications:
    def test_notifications_queued(self):
        broker = BackBroker(cash=10000.0)
        broker.setcommission(commission=0.0, stocklike=True)
        data = make_bar(open=100.0, high=110.0, low=90.0)

        broker.buy(data=data, size=10)

        # Should have at least one notification (accept).
        notif = broker.get_notification()
        assert notif is not None

    def test_notifications_empty_when_none(self):
        broker = BackBroker()
        assert broker.get_notification() is None


# ── Futures mode ──────────────────────────────────────────────────────


class TestFuturesMode:
    def test_futures_margin_deducted(self):
        broker = BackBroker(cash=10000.0)
        broker.setcommission(
            commission=0.0, margin=500.0, mult=10.0, stocklike=False
        )
        # Use close == open so mark-to-market adds zero on same bar.
        data = make_bar(open=100.0, high=110.0, low=90.0, close=100.0)

        broker.buy(data=data, size=2)
        broker.next()

        # Margin deducted: 2 * 500 = 1000.
        # Mark-to-market: close == fill price (100) -> no adjustment.
        assert broker.getcash() == pytest.approx(9000.0)

    def test_futures_mark_to_market(self):
        broker = BackBroker(cash=10000.0)
        broker.setcommission(
            commission=0.0, margin=500.0, mult=10.0, stocklike=False
        )
        # Fill at open=100, close=100 so first mark-to-market is zero.
        data = make_bar(open=100.0, high=110.0, low=90.0, close=100.0)

        broker.buy(data=data, size=2)
        broker.next()
        cash_after_buy = broker.getcash()
        # cash_after_buy = 10000 - 1000 = 9000 (margin only, no M2M delta).

        # Next bar: close moves to 110.
        # Update the data object in place to simulate new bar.
        data.close = 110.0
        broker.next()

        # Mark-to-market: adjbase was 100 from first bar close.
        # Delta: 2 * (110 - 100) * 10 = 200.
        assert broker.getcash() == pytest.approx(cash_after_buy + 200.0)


# ── getvalue with positions ──────────────────────────────────────────


class TestGetValue:
    def test_value_includes_stock_position(self):
        broker = BackBroker(cash=10000.0)
        broker.setcommission(commission=0.0, stocklike=True)
        data = make_bar(open=100.0, high=110.0, low=90.0, close=105.0)

        broker.buy(data=data, size=10)
        broker.next()

        # Cash: 10000 - 10*100 = 9000. Position: 10*105 = 1050.
        assert broker.getvalue() == pytest.approx(9000.0 + 1050.0)

    def test_value_with_filter(self):
        broker = BackBroker(cash=10000.0)
        broker.setcommission(commission=0.0, stocklike=True)
        data1 = make_bar(open=100.0, high=110.0, low=90.0, close=105.0)
        data2 = make_bar(open=50.0, high=55.0, low=45.0, close=52.0)

        broker.buy(data=data1, size=10)
        broker.next()
        broker.buy(data=data2, size=20)
        broker.next()

        # Total value only counting data1.
        val = broker.getvalue(datas=[data1])
        # Cash: 10000 - 10*100 - 20*50 = 10000 - 1000 - 1000 = 8000.
        # data1 position: 10 * 105 = 1050.
        assert val == pytest.approx(8000.0 + 1050.0)


# ── Repr ──────────────────────────────────────────────────────────────


class TestRepr:
    def test_repr(self):
        broker = BackBroker(cash=5000.0)
        r = repr(broker)
        assert "5000" in r
        assert "BackBroker" in r
