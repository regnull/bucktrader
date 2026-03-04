"""Tests for live trading framework (TER-399)."""

from __future__ import annotations

import logging
from datetime import date, datetime, time
from types import SimpleNamespace
from typing import Any

from bucktrader.calendar import TradingCalendar
from bucktrader.cortex import Cortex
from bucktrader.logutils import configure_logging, get_logger
from bucktrader.stores import IBStore, OandaStore
from bucktrader.stores.live import LiveBroker, LiveDataBase


class _LiveStrategy:
    def __init__(self) -> None:
        self.datas: list[Any] = []
        self.data: Any = None
        self.broker: Any = None
        self.env: Any = None
        self.cortex: Any = None
        self._lineiterators = {0: [], 1: [], 2: []}
        self.store_msgs: list[Any] = []
        self.data_msgs: list[Any] = []
        self.bars = 0

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def _next(self) -> None:
        self.bars += 1

    def notify_order(self, order: Any) -> None:
        pass

    def notify_trade(self, trade: Any) -> None:
        pass

    def notify_cashvalue(self, cash: float, value: float) -> None:
        pass

    def notify_fund(self, cash: float, value: float, fv: float, shares: float) -> None:
        pass

    def notify_store(self, msg: Any, *args: Any, **kwargs: Any) -> None:
        self.store_msgs.append((msg, args, kwargs))

    def notify_data(self, data: Any, status: Any, *args: Any, **kwargs: Any) -> None:
        self.data_msgs.append((status, args, kwargs))


class TestStoreBasics:
    def test_store_is_singleton(self):
        a = IBStore()
        b = IBStore()
        assert a is b

    def test_factory_methods_bind_store(self):
        store = OandaStore(token="t", account="a")
        data = store.getdata()
        broker = store.getbroker()
        assert getattr(data, "_store", None) is store
        assert getattr(broker, "_store", None) is store

    def test_store_notifications_roundtrip(self):
        store = IBStore()
        store.put_notification("X", 1, a=2)
        notifs = store.get_notifications()
        assert len(notifs) == 1
        assert notifs[0][0] == "X"
        # Cleared after read.
        assert store.get_notifications() == []


class TestLiveDataAndBroker:
    def test_live_data_queue_load(self):
        data = LiveDataBase(qcheck=0.01)
        data.start()
        data.put_bar(datetime(2024, 1, 2, 10, 0), 1, 2, 0.5, 1.5, 10, 0)
        ok = data.load()
        assert ok is True
        assert data.close[0] == 1.5

    def test_live_broker_order_lifecycle_stub(self):
        broker = LiveBroker(cash=1000)
        broker.start()
        order = broker.buy(owner=None, data=None, size=1)
        assert order.status == order.Status.Accepted
        broker.cancel(order)
        assert order.status == order.Status.Canceled


class TestCalendarAndLogging:
    def test_trading_calendar_nextday_and_schedule(self):
        cal = TradingCalendar(
            holidays=["2024-01-01"],
            earlydays=[("2024-12-24", time(13, 0))],
        )
        # Jan 1 holiday => next day should be Jan 2.
        assert cal._nextday(date(2024, 1, 1)).isoformat() == "2024-01-02"
        _, close = cal.schedule(date(2024, 12, 24))
        assert close.hour == 13

    def test_logging_helpers(self):
        configure_logging(level=logging.DEBUG)
        log = get_logger("bucktrader.test")
        assert log.name == "bucktrader.test"


class TestCortexLiveNotifications:
    def test_cortex_delivers_store_and_data_notifications(self):
        store = IBStore()
        data = store.getdata(qcheck=0.01)
        data.put_status(data.CONNECTED)
        data.put_bar(datetime(2024, 1, 2, 10, 0), 10, 11, 9, 10.5, 100, 0)
        store.put_notification("STORE_OK")

        cortex = Cortex(preload=True, runonce=True)
        cortex.addstore(store)
        cortex.adddata(data)
        cortex.addstrategy(_LiveStrategy)

        results = cortex.run()
        strat = results[0]

        # live mode auto-disables preload/runonce
        assert cortex.p_preload is False
        assert cortex.p_runonce is False

        assert any(msg[0] == "STORE_OK" for msg in strat.store_msgs)
        assert any(msg[0] == data.CONNECTED for msg in strat.data_msgs)
