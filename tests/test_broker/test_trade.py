"""Tests for bucktrader.trade module."""

from datetime import datetime

import pytest

from bucktrader.trade import Trade, TradeStatus, reset_trade_ref_counter


@pytest.fixture(autouse=True)
def _reset_refs():
    """Reset trade ref counter before each test."""
    reset_trade_ref_counter(1)
    yield
    reset_trade_ref_counter(1)


class TestTrade:
    def test_initial_state(self):
        trade = Trade(data="AAPL", tradeid=1)
        assert trade.status == TradeStatus.Created
        assert trade.size == 0.0
        assert trade.price == 0.0
        assert trade.commission == 0.0
        assert trade.pnl == 0.0
        assert trade.pnlcomm == 0.0
        assert trade.isopen is False
        assert trade.isclosed is False
        assert trade.justopened is False

    def test_auto_increment_ref(self):
        t1 = Trade()
        t2 = Trade()
        assert t2.ref == t1.ref + 1

    def test_open_trade(self):
        trade = Trade(data="AAPL")
        dt = datetime(2024, 1, 10)

        trade.update(
            order_ref=1, size=100, price=50.0,
            value=5000.0, commission=5.0, pnl=0.0,
            dt=dt, bar=0,
        )

        assert trade.status == TradeStatus.Open
        assert trade.isopen is True
        assert trade.isclosed is False
        assert trade.justopened is True
        assert trade.size == 100
        assert trade.price == 50.0
        assert trade.commission == 5.0
        assert trade.dtopen == dt
        assert trade.baropen == 0

    def test_close_trade(self):
        trade = Trade(data="AAPL")
        dt_open = datetime(2024, 1, 10)
        dt_close = datetime(2024, 1, 15)

        trade.update(
            order_ref=1, size=100, price=50.0,
            value=5000.0, commission=5.0, pnl=0.0,
            dt=dt_open, bar=0,
        )
        trade.update(
            order_ref=2, size=-100, price=55.0,
            value=5500.0, commission=5.0, pnl=500.0,
            dt=dt_close, bar=5,
        )

        assert trade.status == TradeStatus.Closed
        assert trade.isopen is False
        assert trade.isclosed is True
        assert trade.size == 0
        assert trade.pnl == pytest.approx(500.0)
        assert trade.commission == pytest.approx(10.0)
        assert trade.pnlcomm == pytest.approx(490.0)
        assert trade.dtclose == dt_close
        assert trade.barclose == 5
        assert trade.barlen == 5

    def test_add_to_trade(self):
        """Adding to an existing position updates weighted average price."""
        trade = Trade()

        trade.update(
            order_ref=1, size=100, price=50.0,
            value=5000.0, commission=5.0, pnl=0.0,
            dt=None, bar=0,
        )
        trade.update(
            order_ref=2, size=100, price=60.0,
            value=6000.0, commission=5.0, pnl=0.0,
            dt=None, bar=1,
        )

        assert trade.size == 200
        assert trade.price == pytest.approx(55.0)
        assert trade.commission == pytest.approx(10.0)
        assert trade.isopen is True
        assert trade.justopened is False  # Only true on first entry.

    def test_partial_close(self):
        """Partially closing a trade keeps it open."""
        trade = Trade()
        trade.update(
            order_ref=1, size=100, price=50.0,
            value=5000.0, commission=5.0, pnl=0.0,
        )
        trade.update(
            order_ref=2, size=-50, price=55.0,
            value=2750.0, commission=2.5, pnl=250.0,
        )

        assert trade.size == 50
        assert trade.isopen is True
        assert trade.isclosed is False
        assert trade.pnl == pytest.approx(250.0)

    def test_losing_trade(self):
        trade = Trade()
        trade.update(
            order_ref=1, size=100, price=50.0,
            value=5000.0, commission=5.0, pnl=0.0,
        )
        trade.update(
            order_ref=2, size=-100, price=45.0,
            value=4500.0, commission=5.0, pnl=-500.0,
        )

        assert trade.pnl == pytest.approx(-500.0)
        assert trade.pnlcomm == pytest.approx(-510.0)
        assert trade.isclosed is True

    def test_short_trade(self):
        """Short trade: sell first, buy to close."""
        trade = Trade()
        trade.update(
            order_ref=1, size=-100, price=50.0,
            value=5000.0, commission=5.0, pnl=0.0,
        )
        assert trade.size == -100
        assert trade.isopen is True

        trade.update(
            order_ref=2, size=100, price=45.0,
            value=4500.0, commission=5.0, pnl=500.0,
        )
        assert trade.size == 0
        assert trade.isclosed is True
        assert trade.pnl == pytest.approx(500.0)

    def test_history_recording(self):
        """When historyon=True, each update records a history entry."""
        trade = Trade(historyon=True)
        trade.update(
            order_ref=1, size=100, price=50.0,
            value=5000.0, commission=5.0, pnl=0.0,
        )
        trade.update(
            order_ref=2, size=-100, price=55.0,
            value=5500.0, commission=5.0, pnl=500.0,
        )

        assert len(trade.history) == 2
        # First entry.
        assert trade.history[0].event[0] == 1  # order_ref
        assert trade.history[0].event[1] == 100  # size
        # Second entry.
        assert trade.history[1].event[0] == 2
        assert trade.history[1].event[1] == -100

    def test_history_off_by_default(self):
        trade = Trade()
        trade.update(
            order_ref=1, size=100, price=50.0,
            value=5000.0, commission=5.0, pnl=0.0,
        )
        assert len(trade.history) == 0

    def test_barlen_calculation(self):
        trade = Trade()
        trade.update(
            order_ref=1, size=100, price=50.0,
            value=5000.0, commission=0.0, pnl=0.0,
            bar=10,
        )
        trade.update(
            order_ref=2, size=-100, price=55.0,
            value=5500.0, commission=0.0, pnl=500.0,
            bar=20,
        )
        assert trade.baropen == 10
        assert trade.barclose == 20
        assert trade.barlen == 10

    def test_repr(self):
        trade = Trade()
        r = repr(trade)
        assert "Created" in r

    def test_status_enum(self):
        assert TradeStatus.Created == 0
        assert TradeStatus.Open == 1
        assert TradeStatus.Closed == 2
