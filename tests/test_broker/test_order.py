"""Tests for bucktrader.order module."""

from datetime import datetime

import pytest

from bucktrader.order import (
    ExecType,
    Order,
    OrderData,
    OrderExecutionBit,
    OrderStatus,
    reset_order_ref_counter,
)


@pytest.fixture(autouse=True)
def _reset_refs():
    """Reset order ref counter before each test for deterministic refs."""
    reset_order_ref_counter(1)
    yield
    reset_order_ref_counter(1)


# ── OrderData ─────────────────────────────────────────────────────────


class TestOrderData:
    def test_defaults(self):
        od = OrderData()
        assert od.dt is None
        assert od.size == 0.0
        assert od.remsize == 0.0
        assert od.price == 0.0
        assert od.value == 0.0
        assert od.comm == 0.0
        assert od.pnl == 0.0
        assert od.margin == 0.0

    def test_init_with_dt(self):
        dt = datetime(2024, 1, 15)
        od = OrderData(dt=dt)
        assert od.dt == dt

    def test_clone(self):
        od = OrderData(dt=datetime(2024, 1, 1))
        od.size = 100
        od.price = 50.0
        od.comm = 1.5

        clone = od.clone()
        assert clone.size == 100
        assert clone.price == 50.0
        assert clone.comm == 1.5
        assert clone.dt == od.dt

        # Modifying clone should not affect original.
        clone.size = 200
        assert od.size == 100


# ── OrderExecutionBit ─────────────────────────────────────────────────


class TestOrderExecutionBit:
    def test_creation(self):
        dt = datetime(2024, 6, 1)
        bit = OrderExecutionBit(
            dt=dt, size=50, price=100.0, closed=30, opened=20,
            pnl=150.0, value=5000.0, comm=5.0,
        )
        assert bit.dt == dt
        assert bit.size == 50
        assert bit.price == 100.0
        assert bit.closed == 30
        assert bit.opened == 20
        assert bit.pnl == 150.0
        assert bit.value == 5000.0
        assert bit.comm == 5.0

    def test_defaults(self):
        bit = OrderExecutionBit()
        assert bit.dt is None
        assert bit.size == 0.0
        assert bit.price == 0.0


# ── Order ─────────────────────────────────────────────────────────────


class TestOrder:
    def test_auto_increment_ref(self):
        o1 = Order(size=10)
        o2 = Order(size=20)
        assert o2.ref == o1.ref + 1

    def test_buy_sell_detection(self):
        buy = Order(size=10)
        assert buy.is_buy is True
        assert buy.is_sell is False

        sell = Order(size=-10)
        assert sell.is_buy is False
        assert sell.is_sell is True

    def test_initial_status(self):
        order = Order(size=5)
        assert order.status == OrderStatus.Created
        assert order.alive is True

    def test_created_snapshot(self):
        order = Order(size=100, price=50.0)
        assert order.created.size == 100
        assert order.created.remsize == 100
        assert order.created.price == 50.0

    def test_executed_initial(self):
        order = Order(size=100)
        assert order.executed.remsize == 100
        assert order.executed.size == 0

    def test_status_transitions(self):
        order = Order(size=10)
        dt = datetime(2024, 1, 1)

        order.submit(dt=dt)
        assert order.status == OrderStatus.Submitted
        assert order.created.dt == dt
        assert order.alive is True

        order.accept(dt=dt)
        assert order.status == OrderStatus.Accepted
        assert order.alive is True

        order.partial()
        assert order.status == OrderStatus.Partial
        assert order.alive is True

        order.completed()
        assert order.status == OrderStatus.Completed
        assert order.alive is False

    def test_cancel(self):
        order = Order(size=10)
        order.submit()
        order.accept()
        order.cancel()
        assert order.status == OrderStatus.Canceled
        assert order.alive is False

    def test_expire(self):
        order = Order(size=10)
        order.submit()
        order.accept()
        order.expire()
        assert order.status == OrderStatus.Expired
        assert order.alive is False

    def test_margin_rejection(self):
        order = Order(size=10)
        order.submit()
        order.accept()
        order.margin()
        assert order.status == OrderStatus.Margin
        assert order.alive is False

    def test_reject(self):
        order = Order(size=10)
        order.submit()
        order.reject()
        assert order.status == OrderStatus.Rejected
        assert order.alive is False

    def test_full_execution(self):
        order = Order(size=100, price=50.0)
        dt = datetime(2024, 3, 1)

        order.execute(
            dt=dt, size=100, price=50.0,
            closed=0, opened=100, comm=5.0, pnl=0.0, value=5000.0,
        )

        assert order.status == OrderStatus.Completed
        assert order.executed.size == 100
        assert order.executed.remsize == 0.0
        assert order.executed.price == 50.0
        assert order.executed.comm == 5.0
        assert len(order.execution_bits) == 1

    def test_partial_execution(self):
        order = Order(size=100, price=50.0)

        # First partial fill: 60 units.
        order.execute(
            dt=None, size=60, price=50.0,
            closed=0, opened=60, comm=3.0, pnl=0.0, value=3000.0,
        )
        assert order.status == OrderStatus.Partial
        assert order.executed.size == 60
        assert order.executed.remsize == 40
        assert len(order.execution_bits) == 1

        # Second partial fill: remaining 40 units.
        order.execute(
            dt=None, size=40, price=51.0,
            closed=0, opened=40, comm=2.0, pnl=0.0, value=2040.0,
        )
        assert order.status == OrderStatus.Completed
        assert order.executed.size == 100
        assert order.executed.remsize == 0.0
        assert order.executed.comm == 5.0
        assert len(order.execution_bits) == 2

    def test_weighted_average_price_on_partial(self):
        order = Order(size=100, price=50.0)

        order.execute(
            dt=None, size=60, price=50.0,
            closed=0, opened=60, comm=0, pnl=0, value=3000.0,
        )
        assert order.executed.price == pytest.approx(50.0)

        order.execute(
            dt=None, size=40, price=55.0,
            closed=0, opened=40, comm=0, pnl=0, value=2200.0,
        )
        expected = (50.0 * 60 + 55.0 * 40) / 100
        assert order.executed.price == pytest.approx(expected)

    def test_clone(self):
        order = Order(size=100, price=50.0, exectype=ExecType.Limit)
        clone = order.clone(size=200)
        assert clone.size == 200
        assert clone.price == 50.0
        assert clone.exectype == ExecType.Limit
        assert clone.ref != order.ref  # New unique ref.

    def test_exec_types_enum(self):
        assert ExecType.Market == 0
        assert ExecType.Close == 1
        assert ExecType.Limit == 2
        assert ExecType.Stop == 3
        assert ExecType.StopLimit == 4
        assert ExecType.StopTrail == 5
        assert ExecType.StopTrailLimit == 6
        assert ExecType.Historical == 7

    def test_order_with_validity(self):
        dt = datetime(2024, 12, 31)
        order = Order(size=10, valid=dt)
        assert order.valid == dt

        day_order = Order(size=10, valid=0.0)
        assert day_order.valid == 0.0

    def test_oco_and_parent(self):
        parent = Order(size=10)
        child = Order(size=-10, parent=parent, oco=parent)
        assert child.parent is parent
        assert child.oco is parent

    def test_children_list(self):
        parent = Order(size=10)
        child1 = Order(size=-5, parent=parent)
        parent.children.append(child1)
        assert len(parent.children) == 1
        assert parent.children[0] is child1

    def test_repr(self):
        order = Order(size=10, exectype=ExecType.Market)
        r = repr(order)
        assert "Buy" in r
        assert "Market" in r

    def test_trailing_stop_fields(self):
        order = Order(
            size=-10,
            exectype=ExecType.StopTrail,
            trailamount=2.0,
            trailpercent=0.05,
        )
        assert order.trailamount == 2.0
        assert order.trailpercent == 0.05
        assert order._trail_stop_price is None
