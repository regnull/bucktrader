"""Interactive Brokers store/data/broker stubs."""

from __future__ import annotations

from typing import Any

from bucktrader.stores.base import Store
from bucktrader.stores.live import LiveBroker, LiveDataBase


class IBData(LiveDataBase):
    """IB live data stub."""

    def __init__(
        self,
        *args: Any,
        sectype: str = "STK",
        exchange: str = "SMART",
        currency: str = "",
        rtbar: bool = False,
        historical: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.p_sectype = sectype
        self.p_exchange = exchange
        self.p_currency = currency
        self.p_rtbar = rtbar
        self.p_historical = historical


class IBBroker(LiveBroker):
    """IB broker stub."""


class IBStore(Store):
    """IB store stub with singleton lifecycle and factory methods."""

    DataCls = IBData
    BrokerCls = IBBroker

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 7496,
        clientId: int | None = None,
        reconnect: int = 3,
        timeout: float = 3.0,
        **kwargs: Any,
    ) -> None:
        super().__init__()
        self.p_host = host
        self.p_port = port
        self.p_clientId = clientId
        self.p_reconnect = reconnect
        self.p_timeout = timeout
        self.connected = False

    def start(self, data: Any = None, broker: Any = None) -> None:
        super().start(data=data, broker=broker)
        self.connected = True
        self.put_notification("IB_CONNECTED", host=self.p_host, port=self.p_port)

    def stop(self) -> None:
        self.connected = False
        self.put_notification("IB_DISCONNECTED")
        super().stop()
