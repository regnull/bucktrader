"""Store base classes for live trading integrations."""

from __future__ import annotations

from collections import deque
from typing import Any

from bucktrader.metabase import SingletonBase


class Store(SingletonBase):
    """Singleton connection manager for broker/data integrations."""

    BrokerCls: type | None = None
    DataCls: type | None = None

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._started = False
        self._notifs: deque[tuple[Any, tuple[Any, ...], dict[str, Any]]] = deque()
        self._datas: list[Any] = []
        self._brokers: list[Any] = []

    def start(self, data: Any = None, broker: Any = None) -> None:
        """Start the store connection lifecycle."""
        self._started = True
        if data is not None and data not in self._datas:
            self._datas.append(data)
        if broker is not None and broker not in self._brokers:
            self._brokers.append(broker)

    def stop(self) -> None:
        """Stop the store connection lifecycle."""
        self._started = False

    def getdata(self, *args: Any, **kwargs: Any) -> Any:
        """Create a store-bound data feed."""
        if self.DataCls is None:
            raise ValueError(f"{type(self).__name__} has no DataCls")
        data = self.DataCls(*args, **kwargs)
        data._store = self
        return data

    def getbroker(self, *args: Any, **kwargs: Any) -> Any:
        """Create a store-bound broker."""
        if self.BrokerCls is None:
            raise ValueError(f"{type(self).__name__} has no BrokerCls")
        broker = self.BrokerCls(*args, **kwargs)
        broker._store = self
        return broker

    def put_notification(self, msg: Any, *args: Any, **kwargs: Any) -> None:
        """Queue a generic store notification."""
        self._notifs.append((msg, args, kwargs))

    def get_notifications(self) -> list[tuple[Any, tuple[Any, ...], dict[str, Any]]]:
        """Return and clear pending notifications."""
        notifs = list(self._notifs)
        self._notifs.clear()
        return notifs
