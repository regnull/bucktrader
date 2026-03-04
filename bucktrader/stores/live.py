"""Live data/broker base implementations."""

from __future__ import annotations

import logging
from collections import deque
from datetime import datetime, timezone
from queue import Empty, Queue
from typing import Any

from bucktrader.broker import BrokerBase
from bucktrader.dataseries import date2num
from bucktrader.feed import DataBase, DataStatus
from bucktrader.order import ExecType, Order
from bucktrader.position import Position


logger = logging.getLogger(__name__)


class LiveDataBase(DataBase):
    """Queue-backed live data feed base."""

    LIVE = DataStatus.LIVE
    CONNECTED = DataStatus.CONNECTED
    DISCONNECTED = DataStatus.DISCONNECTED
    CONNBROKEN = DataStatus.CONNBROKEN
    DELAYED = DataStatus.DELAYED

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._queue: Queue[Any] = Queue()
        self._notifs: deque[tuple[Any, tuple[Any, ...], dict[str, Any]]] = deque()
        self._store: Any = kwargs.pop("_store", None)

    def islive(self) -> bool:
        return True

    def put_bar(
        self,
        dt: datetime,
        open_: float,
        high: float,
        low: float,
        close: float,
        volume: float = 0.0,
        openinterest: float = 0.0,
    ) -> None:
        """Push a live bar into the feed queue."""
        self._queue.put(
            (
                date2num(dt),
                open_,
                high,
                low,
                close,
                volume,
                openinterest,
            )
        )

    def put_status(self, status: Any, *args: Any, **kwargs: Any) -> None:
        """Queue a live status notification."""
        self._notifs.append((status, args, kwargs))

    def get_notifications(self) -> list[tuple[Any, tuple[Any, ...], dict[str, Any]]]:
        """Return and clear data status notifications."""
        notifs = list(self._notifs)
        self._notifs.clear()
        return notifs

    def _load(self) -> bool:
        timeout = float(self.p_qcheck or 0.0)
        try:
            if timeout > 0:
                item = self._queue.get(timeout=timeout)
            else:
                item = self._queue.get_nowait()
        except Empty:
            return False

        if isinstance(item, dict):
            status = item.get("status")
            if status is not None:
                self.put_status(status, *item.get("args", ()), **item.get("kwargs", {}))
            return False

        if not isinstance(item, tuple) or len(item) < 5:
            logger.warning("Ignoring malformed live bar payload: %r", item)
            return False

        dt, o, h, l, c, *rest = item
        v = rest[0] if len(rest) > 0 else 0.0
        oi = rest[1] if len(rest) > 1 else 0.0

        self.datetime[0] = float(dt)
        self.open[0] = float(o)
        self.high[0] = float(h)
        self.low[0] = float(l)
        self.close[0] = float(c)
        self.volume[0] = float(v)
        self.openinterest[0] = float(oi)
        return True


class LiveBroker(BrokerBase):
    """Minimal live broker stub for API routing integrations."""

    def __init__(self, cash: float = 10_000.0) -> None:
        super().__init__()
        self.cash = float(cash)
        self._positions: dict[Any, Position] = {}
        self._pending: dict[int, Order] = {}
        self._store: Any = None
        self._fundshares: float = 0.0
        self._fundvalue: float = cash

    def start(self) -> None:
        self._fundshares = 1.0 if self.cash else 0.0

    def next(self) -> None:
        # In real integrations this polls API fills/position sync.
        return

    def buy(
        self,
        owner: Any,
        data: Any,
        size: float,
        price: float | None = None,
        plimit: float | None = None,
        exectype: ExecType = ExecType.Market,
        valid: datetime | float | int | None = None,
        tradeid: int = 0,
        oco: Order | None = None,
        trailamount: float | None = None,
        trailpercent: float | None = None,
        parent: Order | None = None,
        transmit: bool = True,
        **kwargs: Any,
    ) -> Order:
        return self._submit(
            data=data,
            size=abs(size),
            price=price,
            plimit=plimit,
            exectype=exectype,
            valid=valid,
            tradeid=tradeid,
            oco=oco,
            parent=parent,
            transmit=transmit,
            trailamount=trailamount,
            trailpercent=trailpercent,
            **kwargs,
        )

    def sell(
        self,
        owner: Any,
        data: Any,
        size: float,
        price: float | None = None,
        plimit: float | None = None,
        exectype: ExecType = ExecType.Market,
        valid: datetime | float | int | None = None,
        tradeid: int = 0,
        oco: Order | None = None,
        trailamount: float | None = None,
        trailpercent: float | None = None,
        parent: Order | None = None,
        transmit: bool = True,
        **kwargs: Any,
    ) -> Order:
        return self._submit(
            data=data,
            size=-abs(size),
            price=price,
            plimit=plimit,
            exectype=exectype,
            valid=valid,
            tradeid=tradeid,
            oco=oco,
            parent=parent,
            transmit=transmit,
            trailamount=trailamount,
            trailpercent=trailpercent,
            **kwargs,
        )

    def _submit(
        self,
        data: Any,
        size: float,
        price: float | None = None,
        plimit: float | None = None,
        exectype: ExecType = ExecType.Market,
        valid: datetime | float | int | None = None,
        tradeid: int = 0,
        oco: Order | None = None,
        parent: Order | None = None,
        transmit: bool = True,
        trailamount: float | None = None,
        trailpercent: float | None = None,
        **kwargs: Any,
    ) -> Order:
        order = Order(
            data=data,
            size=size,
            price=price,
            pricelimit=plimit,
            exectype=exectype,
            valid=valid,
            tradeid=tradeid,
            oco=oco,
            parent=parent,
            transmit=transmit,
            trailamount=trailamount,
            trailpercent=trailpercent,
            **kwargs,
        )
        now = datetime.now(timezone.utc)
        order.submit(now)
        order.accept(now)
        self._pending[order.ref] = order
        self.notify(order)
        return order

    def cancel(self, order: Order) -> None:
        if order.ref in self._pending:
            order.cancel()
            self._pending.pop(order.ref, None)
            self.notify(order)

    def getvalue(self, datas: list[Any] | None = None) -> float:
        return self.cash

    def getcash(self) -> float:
        return self.cash

    def getposition(self, data: Any) -> Position:
        if data not in self._positions:
            self._positions[data] = Position()
        return self._positions[data]

    def get_fundshares(self) -> float:
        return self._fundshares

    def get_fundvalue(self) -> float:
        return self._fundvalue if self._fundshares == 0 else self.getvalue() / self._fundshares
