"""Order, OrderData, and OrderExecutionBit classes for the bucktrader framework.

Orders represent instructions to buy or sell a financial instrument. They progress
through a lifecycle from Created to a terminal state (Completed, Canceled, etc.).
"""

from __future__ import annotations

import itertools
from datetime import datetime
from enum import IntEnum
from typing import Any


class OrderStatus(IntEnum):
    """Status lifecycle for an order."""

    Created = 0
    Submitted = 1
    Accepted = 2
    Partial = 3
    Completed = 4
    Canceled = 5
    Expired = 6
    Margin = 7
    Rejected = 8


class ExecType(IntEnum):
    """Order execution type."""

    Market = 0
    Close = 1
    Limit = 2
    Stop = 3
    StopLimit = 4
    StopTrail = 5
    StopTrailLimit = 6
    Historical = 7


class OrderData:
    """Tracks execution details for an order at a point in time.

    Used for both the `created` snapshot (state at creation) and the
    `executed` accumulator (running totals across partial fills).
    """

    def __init__(self, dt: datetime | None = None):
        self.dt: datetime | None = dt
        self.size: float = 0.0
        self.remsize: float = 0.0
        self.price: float = 0.0
        self.value: float = 0.0
        self.comm: float = 0.0
        self.pnl: float = 0.0
        self.margin: float = 0.0

    def clone(self) -> OrderData:
        """Return a shallow copy of this OrderData."""
        od = OrderData(dt=self.dt)
        od.size = self.size
        od.remsize = self.remsize
        od.price = self.price
        od.value = self.value
        od.comm = self.comm
        od.pnl = self.pnl
        od.margin = self.margin
        return od

    def __repr__(self) -> str:
        return (
            f"OrderData(dt={self.dt}, size={self.size}, remsize={self.remsize}, "
            f"price={self.price}, value={self.value}, comm={self.comm}, "
            f"pnl={self.pnl}, margin={self.margin})"
        )


class OrderExecutionBit:
    """Records a single partial (or complete) fill event.

    Each time an order is partially or fully executed, an execution bit
    is appended to the order's execution history.
    """

    def __init__(
        self,
        dt: datetime | None = None,
        size: float = 0.0,
        price: float = 0.0,
        closed: float = 0.0,
        opened: float = 0.0,
        pnl: float = 0.0,
        value: float = 0.0,
        comm: float = 0.0,
    ):
        self.dt = dt
        self.size = size
        self.price = price
        self.closed = closed
        self.opened = opened
        self.pnl = pnl
        self.value = value
        self.comm = comm

    def __repr__(self) -> str:
        return (
            f"OrderExecutionBit(dt={self.dt}, size={self.size}, price={self.price}, "
            f"closed={self.closed}, opened={self.opened}, pnl={self.pnl}, "
            f"value={self.value}, comm={self.comm})"
        )


# Global auto-increment counter for unique order references.
_ref_counter = itertools.count(1)


def _next_ref() -> int:
    """Return the next unique order reference number."""
    return next(_ref_counter)


def reset_order_ref_counter(start: int = 1) -> None:
    """Reset the global order reference counter (useful for testing)."""
    global _ref_counter
    _ref_counter = itertools.count(start)


class Order:
    """Represents an instruction to buy or sell a financial instrument.

    Attributes:
        ref: Unique auto-incrementing reference number.
        status: Current status in the order lifecycle.
        data: The data feed this order targets.
        size: Requested size (positive=buy, negative=sell).
        price: Requested price (meaning depends on exectype).
        pricelimit: Price limit for StopLimit orders.
        exectype: Execution type (Market, Limit, Stop, etc.).
        valid: Validity constraint (None=GTC, datetime, or float(0.0)=DAY).
        tradeid: Identifier grouping related trades.
        oco: Reference to another order in a One-Cancels-Other group.
        parent: Parent order (for bracket order children).
        transmit: Whether to transmit immediately.
        created: OrderData snapshot at creation time.
        executed: OrderData accumulator tracking execution progress.
        trailamount: Trailing stop distance in price units.
        trailpercent: Trailing stop distance as a fraction (0.01 = 1%).
        info: General-purpose dict for user/broker metadata.
    """

    # Expose enums as class attributes for convenient access.
    Status = OrderStatus
    ExecTypes = ExecType

    # Side constants
    Buy = "buy"
    Sell = "sell"

    def __init__(
        self,
        data: Any = None,
        size: float = 0.0,
        price: float | None = None,
        pricelimit: float | None = None,
        exectype: ExecType = ExecType.Market,
        valid: datetime | float | int | None = None,
        tradeid: int = 0,
        oco: Order | None = None,
        parent: Order | None = None,
        transmit: bool = True,
        trailamount: float | None = None,
        trailpercent: float | None = None,
        simulated: bool = False,
        **kwargs: Any,
    ):
        self.ref = _next_ref()
        self.data = data
        self.size = size
        self.price = price
        self.pricelimit = pricelimit
        self.exectype = exectype
        self.valid = valid
        self.tradeid = tradeid
        self.oco = oco
        self.parent = parent
        self.transmit = transmit
        self.trailamount = trailamount
        self.trailpercent = trailpercent
        self.simulated = simulated
        self.info: dict[str, Any] = dict(kwargs)

        # Children orders (for bracket orders).
        self.children: list[Order] = []

        # Status begins at Created.
        self.status = OrderStatus.Created

        # Snapshot at creation time.
        self.created = OrderData()
        self.created.size = size
        self.created.remsize = size
        self.created.price = price if price is not None else 0.0
        self.created.dt = None  # Set by broker when submitted.

        # Accumulator for execution.
        self.executed = OrderData()
        self.executed.remsize = size

        # History of execution bits.
        self.execution_bits: list[OrderExecutionBit] = []

        # Trailing stop internal tracking price.
        self._trail_stop_price: float | None = None

    # ── Convenience properties ────────────────────────────────────────

    @property
    def is_buy(self) -> bool:
        """True if this is a buy order (positive size)."""
        return self.size > 0

    @property
    def is_sell(self) -> bool:
        """True if this is a sell order (negative size)."""
        return self.size < 0

    @property
    def alive(self) -> bool:
        """True if the order may still be filled (not in a terminal state)."""
        return self.status in (
            OrderStatus.Created,
            OrderStatus.Submitted,
            OrderStatus.Accepted,
            OrderStatus.Partial,
        )

    # ── Status transition helpers ─────────────────────────────────────

    def submit(self, dt: datetime | None = None) -> OrderStatus:
        """Transition to Submitted status."""
        self.status = OrderStatus.Submitted
        self.created.dt = dt
        return self.status

    def accept(self, dt: datetime | None = None) -> OrderStatus:
        """Transition to Accepted status."""
        self.status = OrderStatus.Accepted
        self.executed.dt = dt
        return self.status

    def partial(self) -> OrderStatus:
        """Transition to Partial status."""
        self.status = OrderStatus.Partial
        return self.status

    def completed(self) -> OrderStatus:
        """Transition to Completed status."""
        self.status = OrderStatus.Completed
        return self.status

    def cancel(self) -> OrderStatus:
        """Transition to Canceled status."""
        self.status = OrderStatus.Canceled
        return self.status

    def expire(self) -> OrderStatus:
        """Transition to Expired status."""
        self.status = OrderStatus.Expired
        return self.status

    def margin(self) -> OrderStatus:
        """Transition to Margin (rejected for margin) status."""
        self.status = OrderStatus.Margin
        return self.status

    def reject(self) -> OrderStatus:
        """Transition to Rejected status."""
        self.status = OrderStatus.Rejected
        return self.status

    def execute(
        self,
        dt: datetime | None,
        size: float,
        price: float,
        closed: float,
        opened: float,
        comm: float,
        pnl: float,
        value: float,
    ) -> None:
        """Record a (partial or full) execution against this order.

        Updates the executed accumulator, appends an execution bit,
        and transitions status to Partial or Completed.
        """
        # Update executed accumulator.
        self.executed.dt = dt

        # Weighted-average execution price.
        old_size = self.executed.size
        if abs(old_size) + abs(size) != 0:
            self.executed.price = (
                self.executed.price * abs(old_size) + price * abs(size)
            ) / (abs(old_size) + abs(size))

        self.executed.size += size
        self.executed.remsize -= size
        self.executed.value += value
        self.executed.comm += comm
        self.executed.pnl += pnl

        # Record execution bit.
        bit = OrderExecutionBit(
            dt=dt,
            size=size,
            price=price,
            closed=closed,
            opened=opened,
            pnl=pnl,
            value=value,
            comm=comm,
        )
        self.execution_bits.append(bit)

        # Transition status.
        if abs(self.executed.remsize) < 1e-9:
            self.executed.remsize = 0.0
            self.completed()
        else:
            self.partial()

    def clone(
        self,
        data: Any | None = None,
        size: float | None = None,
        price: float | None = None,
        exectype: ExecType | None = None,
    ) -> Order:
        """Create a similar order, reusing most parameters."""
        return Order(
            data=data if data is not None else self.data,
            size=size if size is not None else self.size,
            price=price if price is not None else self.price,
            pricelimit=self.pricelimit,
            exectype=exectype if exectype is not None else self.exectype,
            valid=self.valid,
            tradeid=self.tradeid,
            trailamount=self.trailamount,
            trailpercent=self.trailpercent,
        )

    def __repr__(self) -> str:
        side = "Buy" if self.is_buy else "Sell"
        return (
            f"Order(ref={self.ref}, {side}, size={self.size}, "
            f"exectype={self.exectype.name}, status={self.status.name})"
        )
