"""Tests for bucktrader.position module."""

from datetime import datetime

import pytest

from bucktrader.position import Position


class TestPosition:
    def test_initial_flat(self):
        pos = Position()
        assert pos.size == 0.0
        assert pos.price == 0.0
        assert pos.is_flat is True
        assert pos.is_long is False
        assert pos.is_short is False
        assert bool(pos) is False

    def test_open_long(self):
        pos = Position()
        opened, closed, pnl = pos.update(100, 50.0)
        assert pos.size == 100
        assert pos.price == 50.0
        assert pos.is_long is True
        assert bool(pos) is True
        assert opened == 100
        assert closed == 0
        assert pnl == 0.0

    def test_open_short(self):
        pos = Position()
        opened, closed, pnl = pos.update(-50, 30.0)
        assert pos.size == -50
        assert pos.price == 30.0
        assert pos.is_short is True
        assert opened == -50
        assert closed == 0
        assert pnl == 0.0

    def test_add_to_long(self):
        """Adding to a long position uses weighted average price."""
        pos = Position()
        pos.update(100, 50.0)
        opened, closed, pnl = pos.update(100, 60.0)

        assert pos.size == 200
        assert pos.price == pytest.approx(55.0)  # (100*50 + 100*60) / 200
        assert opened == 100
        assert closed == 0
        assert pnl == 0.0

    def test_add_to_short(self):
        """Adding to a short position uses weighted average price."""
        pos = Position()
        pos.update(-100, 50.0)
        opened, closed, pnl = pos.update(-100, 40.0)

        assert pos.size == -200
        assert pos.price == pytest.approx(45.0)
        assert opened == -100
        assert closed == 0

    def test_partial_close_long(self):
        """Reducing a long position keeps the average entry price."""
        pos = Position()
        pos.update(100, 50.0)
        opened, closed, pnl = pos.update(-40, 60.0)

        assert pos.size == 60
        assert pos.price == pytest.approx(50.0)  # Price stays on reduction.
        assert opened == 0
        assert closed == -40
        # P&L: -(-40) * (60 - 50) = 40 * 10 = 400.
        assert pnl == pytest.approx(400.0)

    def test_full_close_long(self):
        """Fully closing a long position."""
        pos = Position()
        pos.update(100, 50.0)
        opened, closed, pnl = pos.update(-100, 55.0)

        assert pos.size == 0
        assert pos.is_flat is True
        assert closed == -100
        assert opened == 0
        # P&L: -(-100) * (55 - 50) = 100 * 5 = 500.
        assert pnl == pytest.approx(500.0)

    def test_full_close_short(self):
        """Fully closing a short position."""
        pos = Position()
        pos.update(-100, 50.0)
        opened, closed, pnl = pos.update(100, 45.0)

        assert pos.size == 0
        assert closed == 100
        assert opened == 0
        # P&L: -(100) * (45 - 50) = -100 * (-5) = 500.
        assert pnl == pytest.approx(500.0)

    def test_reverse_long_to_short(self):
        """Reversing from long to short closes old and opens new."""
        pos = Position()
        pos.update(100, 50.0)
        opened, closed, pnl = pos.update(-150, 60.0)

        assert pos.size == -50
        assert pos.price == pytest.approx(60.0)  # New position at trade price.
        assert closed == -100  # Closed entire long.
        assert opened == -50  # Opened new short.
        # P&L on closed: -(-100) * (60 - 50) = 1000.
        assert pnl == pytest.approx(1000.0)

    def test_reverse_short_to_long(self):
        """Reversing from short to long."""
        pos = Position()
        pos.update(-100, 50.0)
        opened, closed, pnl = pos.update(150, 40.0)

        assert pos.size == 50
        assert pos.price == pytest.approx(40.0)
        assert closed == 100
        assert opened == 50
        # P&L on closed: -(100) * (40 - 50) = 1000.
        assert pnl == pytest.approx(1000.0)

    def test_datetime_tracking(self):
        pos = Position()
        dt = datetime(2024, 6, 15)
        pos.update(100, 50.0, dt=dt)
        assert pos.datetime == dt

    def test_adjbase_updated(self):
        """adjbase should be updated to trade price on each update."""
        pos = Position()
        pos.update(100, 50.0)
        assert pos.adjbase == 50.0

        pos.update(-50, 55.0)
        assert pos.adjbase == 55.0

    def test_multiple_adds_weighted_avg(self):
        """Multiple additions maintain correct weighted average."""
        pos = Position()
        pos.update(100, 10.0)
        pos.update(200, 20.0)
        pos.update(300, 30.0)

        # (100*10 + 200*20 + 300*30) / 600 = (1000+4000+9000)/600 = 23.33...
        assert pos.size == 600
        assert pos.price == pytest.approx(14000.0 / 600.0)

    def test_losing_trade(self):
        """Closing at a loss yields negative P&L."""
        pos = Position()
        pos.update(100, 50.0)
        opened, closed, pnl = pos.update(-100, 40.0)

        # P&L: -(-100) * (40 - 50) = 100 * (-10) = -1000.
        assert pnl == pytest.approx(-1000.0)

    def test_repr(self):
        pos = Position(size=10, price=50.0)
        assert "10" in repr(pos)
        assert "50.0" in repr(pos)
