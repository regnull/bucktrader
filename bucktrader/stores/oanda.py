"""OANDA store/data/broker stubs."""

from __future__ import annotations

from typing import Any

from bucktrader.stores.base import Store
from bucktrader.stores.live import LiveBroker, LiveDataBase


class OandaData(LiveDataBase):
    """OANDA live data stub."""

    def __init__(
        self,
        *args: Any,
        granularity: str = "M1",
        practice: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.p_granularity = granularity
        self.p_practice = practice


class OandaBroker(LiveBroker):
    """OANDA broker stub."""


class OandaStore(Store):
    """OANDA store stub with singleton lifecycle and factory methods."""

    DataCls = OandaData
    BrokerCls = OandaBroker

    def __init__(
        self,
        token: str = "",
        account: str = "",
        practice: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__()
        self.p_token = token
        self.p_account = account
        self.p_practice = practice
        self.connected = False

    def start(self, data: Any = None, broker: Any = None) -> None:
        super().start(data=data, broker=broker)
        self.connected = True
        self.put_notification("OANDA_CONNECTED", account=self.p_account)

    def stop(self) -> None:
        self.connected = False
        self.put_notification("OANDA_DISCONNECTED")
        super().stop()
