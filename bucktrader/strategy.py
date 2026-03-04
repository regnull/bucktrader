"""Strategy class for the bucktrader framework.

A Strategy is the user's trading logic. It receives market data, evaluates
conditions using indicators, and issues orders through a broker.

Lifecycle:
    constructor()   - Declare indicators, set up state
    start()         - Called once before backtesting begins
    prenext()       - Called for each bar during warmup (min period not yet met)
    nextstart()     - Called exactly once when min period is first met
    next()          - Called for each bar after warmup (main trading logic)
    stop()          - Called once after backtesting ends
"""

from __future__ import annotations

from typing import Any

from bucktrader.order import ExecType, Order, OrderStatus
from bucktrader.position import Position
from bucktrader.sizers import FixedSize, Sizer
from bucktrader.signal import SignalStrategy, SignalType


class Strategy(SignalStrategy):
    """Base class for all trading strategies.

    Users subclass Strategy and override ``__init__`` (to declare indicators)
    and ``next()`` (to implement trading logic). The framework calls lifecycle
    hooks in order: start, prenext/nextstart/next (per bar), stop.

    Data feeds, broker, and environment references are wired up by the Cortex
    engine before ``start()`` is called. For standalone testing, they can be
    set directly.

    Attributes:
        data: First data feed (alias for datas[0]).
        datas: List of all data feeds.
        dnames: Dict mapping data feed names to feed objects.
        broker: The broker instance.
        env: Reference to the Cortex engine.
        cortex: Alias for env.
        _orders: List of all orders created by this strategy.
        _trades: Dict mapping data feeds to lists of trades.
        stats: Observers collection.
        analyzers: Analyzers collection.
    """

    # Subclasses may declare params as a tuple of (name, default) pairs.
    params = ()

    def __init__(self) -> None:
        super().__init__()

        # Data feeds -- wired by Cortex or set directly for testing.
        self.datas: list[Any] = []
        self.data: Any = None
        self.dnames: dict[str, Any] = {}

        # Environment references -- wired by Cortex.
        self.env: Any = None
        self.broker: Any = None

        # Order and trade tracking.
        self._orders: list[Order] = []
        self._trades: dict[Any, list[Any]] = {}

        # Observers and analyzers -- wired by Cortex.
        self.stats: list[Any] = []
        self.analyzers: list[Any] = []

        # Internal sizer.
        self._sizer: Sizer = FixedSize()

        # Minimum period tracking.
        self._minperiod: int = 1
        self._prenext_count: int = 0
        self._nextstart_called: bool = False

        # Parameter support: build params from class-level declaration.
        self._params: dict[str, Any] = {}
        for key, default in self.__class__.params:
            self._params[key] = default

        # Child iterator collections (for compatibility with MetaLineIterator).
        self._lineiterators: dict[int, list[Any]] = {
            0: [],  # IndType
            1: [],  # StratType
            2: [],  # ObsType
        }

    @property
    def p(self) -> _ParamsAccessor:
        """Attribute-style access to strategy params."""
        return _ParamsAccessor(self._params)

    @property
    def cortex(self) -> Any:
        """Alias for env (reference to the Cortex engine)."""
        return self.env

    @cortex.setter
    def cortex(self, value: Any) -> None:
        self.env = value

    # ------------------------------------------------------------------
    # Data feed setup
    # ------------------------------------------------------------------

    def setdatas(self, datas: list[Any]) -> None:
        """Set the data feeds for this strategy.

        Creates convenience attributes: data, data0, data1, etc.
        Also populates dnames from feeds with a ``_name`` attribute.
        """
        self.datas = list(datas)
        self.data = datas[0] if datas else None

        for idx, d in enumerate(datas):
            setattr(self, f"data{idx}", d)

        self.dnames = {}
        for d in datas:
            name = getattr(d, "_name", None) or getattr(d, "name", None)
            if name:
                self.dnames[name] = d

    # ------------------------------------------------------------------
    # Sizer management
    # ------------------------------------------------------------------

    def setsizer(self, sizer: Sizer) -> None:
        """Set the position sizer for this strategy."""
        self._sizer = sizer
        sizer.strategy = self
        sizer.broker = self.broker

    def getsizer(self) -> Sizer:
        """Return the current position sizer."""
        return self._sizer

    def _getsizing(self, data: Any, isbuy: bool) -> float:
        """Calculate order size using the sizer.

        Args:
            data: Data feed being traded.
            isbuy: True for buy, False for sell.

        Returns:
            The computed order size.
        """
        comminfo = self.broker.getcommissioninfo(data)
        cash = self.broker.getcash()
        # Ensure sizer has broker reference.
        self._sizer.broker = self.broker
        return self._sizer.getsizing(comminfo, cash, data, isbuy)

    # ------------------------------------------------------------------
    # Lifecycle hooks (override in subclass)
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Called once before backtesting begins.

        Override to perform setup that needs the broker/data to be ready.
        """

    def prenext(self) -> None:
        """Called for each bar during warmup (min period not yet met).

        Indicators may not have valid values yet. Override if you need
        to track warmup state.
        """

    def nextstart(self) -> None:
        """Called exactly once when the minimum period is first met.

        Default implementation delegates to ``next()``. Override to
        perform one-time initialization that requires valid indicator data.
        """
        self.next()

    def next(self) -> None:
        """Called for each bar after warmup. Main trading logic goes here.

        Override this method to implement your strategy.
        """

    def next_open(self) -> None:
        """Called before broker processes orders in cheat-on-open mode.

        Only called when ``cortex.params.cheat_on_open=True``.
        Override to place orders using the current bar's open price.
        """

    def stop(self) -> None:
        """Called once after backtesting ends.

        Override to perform cleanup or final analysis.
        """

    # ------------------------------------------------------------------
    # Internal bar dispatch (called by Cortex or test harness)
    # ------------------------------------------------------------------

    def _onbar(self, bar_index: int) -> None:
        """Dispatch the correct lifecycle hook for the current bar.

        Args:
            bar_index: The 1-based bar count (number of bars processed).
        """
        if bar_index < self._minperiod:
            self._prenext_count += 1
            self.prenext()
        elif not self._nextstart_called:
            self._nextstart_called = True
            self.nextstart()
        else:
            self.next()

    # ------------------------------------------------------------------
    # Order API
    # ------------------------------------------------------------------

    def buy(
        self,
        data: Any = None,
        size: float | None = None,
        price: float | None = None,
        plimit: float | None = None,
        exectype: ExecType | None = None,
        valid: Any = None,
        tradeid: int = 0,
        oco: Order | None = None,
        trailamount: float | None = None,
        trailpercent: float | None = None,
        parent: Order | None = None,
        transmit: bool = True,
        **kwargs: Any,
    ) -> Order:
        """Submit a buy order.

        Args:
            data: Data feed to trade (default: first data feed).
            size: Order size (default: use sizer).
            price: Limit/stop price.
            plimit: Price limit for StopLimit orders.
            exectype: Execution type (default: Market).
            valid: Order validity.
            tradeid: Trade group identifier.
            oco: One-Cancels-Other linked order.
            trailamount: Trailing stop distance (absolute).
            trailpercent: Trailing stop distance (percentage).
            parent: Parent order (for bracket orders).
            transmit: Submit immediately.

        Returns:
            The created Order object.
        """
        if data is None:
            data = self.data
        if size is None:
            size = self._getsizing(data, isbuy=True)
        if exectype is None:
            exectype = ExecType.Market

        order = self.broker.buy(
            owner=self,
            data=data,
            size=size,
            price=price,
            plimit=plimit,
            exectype=exectype,
            valid=valid,
            tradeid=tradeid,
            oco=oco,
            trailamount=trailamount,
            trailpercent=trailpercent,
            parent=parent,
            transmit=transmit,
            **kwargs,
        )
        self._orders.append(order)
        return order

    def sell(
        self,
        data: Any = None,
        size: float | None = None,
        price: float | None = None,
        plimit: float | None = None,
        exectype: ExecType | None = None,
        valid: Any = None,
        tradeid: int = 0,
        oco: Order | None = None,
        trailamount: float | None = None,
        trailpercent: float | None = None,
        parent: Order | None = None,
        transmit: bool = True,
        **kwargs: Any,
    ) -> Order:
        """Submit a sell order.

        Args:
            data: Data feed to trade (default: first data feed).
            size: Order size (default: use sizer).
            price: Limit/stop price.
            plimit: Price limit for StopLimit orders.
            exectype: Execution type (default: Market).
            valid: Order validity.
            tradeid: Trade group identifier.
            oco: One-Cancels-Other linked order.
            trailamount: Trailing stop distance (absolute).
            trailpercent: Trailing stop distance (percentage).
            parent: Parent order (for bracket orders).
            transmit: Submit immediately.

        Returns:
            The created Order object.
        """
        if data is None:
            data = self.data
        if size is None:
            size = self._getsizing(data, isbuy=False)
        if exectype is None:
            exectype = ExecType.Market

        order = self.broker.sell(
            owner=self,
            data=data,
            size=size,
            price=price,
            plimit=plimit,
            exectype=exectype,
            valid=valid,
            tradeid=tradeid,
            oco=oco,
            trailamount=trailamount,
            trailpercent=trailpercent,
            parent=parent,
            transmit=transmit,
            **kwargs,
        )
        self._orders.append(order)
        return order

    def close(
        self,
        data: Any = None,
        size: float | None = None,
        **kwargs: Any,
    ) -> Order | None:
        """Close the entire position on the given data feed.

        Issues a sell for a long position or a buy for a short position.

        Args:
            data: Data feed (default: first data feed).
            size: Override close size (default: entire position).

        Returns:
            The created Order, or None if position is flat.
        """
        if data is None:
            data = self.data
        pos = self.getposition(data)
        pos_size = pos.size

        if pos_size == 0:
            return None

        if size is None:
            size = abs(pos_size)

        if pos_size > 0:
            return self.sell(data=data, size=size, **kwargs)
        else:
            return self.buy(data=data, size=size, **kwargs)

    def cancel(self, order: Order) -> None:
        """Cancel a pending order.

        Args:
            order: The order to cancel.
        """
        self.broker.cancel(order)

    # ------------------------------------------------------------------
    # Target-based order methods
    # ------------------------------------------------------------------

    def order_target_size(
        self,
        data: Any = None,
        target: float = 0,
        **kwargs: Any,
    ) -> Order | None:
        """Adjust position to reach a target size.

        Buys or sells the difference between current position and target.

        Args:
            data: Data feed (default: first data feed).
            target: Desired position size (positive=long, negative=short).

        Returns:
            The created Order, or None if no adjustment needed.
        """
        if data is None:
            data = self.data

        pos = self.getposition(data)
        diff = target - pos.size

        if diff == 0:
            return None

        if diff > 0:
            return self.buy(data=data, size=abs(diff), **kwargs)
        else:
            return self.sell(data=data, size=abs(diff), **kwargs)

    def order_target_value(
        self,
        data: Any = None,
        target: float = 0.0,
        price: float | None = None,
        **kwargs: Any,
    ) -> Order | None:
        """Adjust position to reach a target portfolio value.

        Args:
            data: Data feed (default: first data feed).
            target: Desired position value in currency.
            price: Price to use for calculation (default: current close).

        Returns:
            The created Order, or None if no adjustment needed.
        """
        if data is None:
            data = self.data

        if price is None:
            price = _get_close_price(data)

        if price is None or price <= 0:
            return None

        pos = self.getposition(data)
        current_value = pos.size * price
        diff_value = target - current_value
        diff_size = diff_value / price

        if abs(diff_size) < 1e-9:
            return None

        if diff_size > 0:
            return self.buy(data=data, size=abs(diff_size), price=price, **kwargs)
        else:
            return self.sell(data=data, size=abs(diff_size), price=price, **kwargs)

    def order_target_percent(
        self,
        data: Any = None,
        target: float = 0.0,
        **kwargs: Any,
    ) -> Order | None:
        """Adjust position to reach a target as a percentage of portfolio value.

        Args:
            data: Data feed (default: first data feed).
            target: Desired position as fraction of portfolio (0.5 = 50%).

        Returns:
            The created Order, or None if no adjustment needed.
        """
        if data is None:
            data = self.data

        portfolio_value = self.broker.getvalue()
        target_value = portfolio_value * target

        return self.order_target_value(data=data, target=target_value, **kwargs)

    # ------------------------------------------------------------------
    # Bracket orders
    # ------------------------------------------------------------------

    def buy_bracket(
        self,
        data: Any = None,
        size: float | None = None,
        price: float | None = None,
        stopprice: float | None = None,
        stopargs: dict[str, Any] | None = None,
        limitprice: float | None = None,
        limitargs: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[Order]:
        """Submit a buy bracket order (entry + stop loss + take profit).

        Returns:
            A list of [main_order, stop_order, limit_order].
        """
        if data is None:
            data = self.data
        if stopargs is None:
            stopargs = {}
        if limitargs is None:
            limitargs = {}

        # Main entry order (do not transmit yet).
        main_order = self.buy(
            data=data,
            size=size,
            price=price,
            transmit=False,
            **kwargs,
        )

        # Stop loss order (sell stop below entry).
        stop_order = self.sell(
            data=data,
            size=main_order.size,
            price=stopprice,
            exectype=ExecType.Stop,
            parent=main_order,
            transmit=False,
            **stopargs,
        )

        # Take profit order (sell limit above entry). Transmit to activate all.
        limit_order = self.sell(
            data=data,
            size=main_order.size,
            price=limitprice,
            exectype=ExecType.Limit,
            parent=main_order,
            transmit=True,
            **limitargs,
        )

        return [main_order, stop_order, limit_order]

    def sell_bracket(
        self,
        data: Any = None,
        size: float | None = None,
        price: float | None = None,
        stopprice: float | None = None,
        stopargs: dict[str, Any] | None = None,
        limitprice: float | None = None,
        limitargs: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[Order]:
        """Submit a sell bracket order (entry + stop loss + take profit).

        Returns:
            A list of [main_order, stop_order, limit_order].
        """
        if data is None:
            data = self.data
        if stopargs is None:
            stopargs = {}
        if limitargs is None:
            limitargs = {}

        # Main entry order (do not transmit yet).
        main_order = self.sell(
            data=data,
            size=size,
            price=price,
            transmit=False,
            **kwargs,
        )

        # Stop loss order (buy stop above entry).
        stop_order = self.buy(
            data=data,
            size=abs(main_order.size),
            price=stopprice,
            exectype=ExecType.Stop,
            parent=main_order,
            transmit=False,
            **stopargs,
        )

        # Take profit order (buy limit below entry). Transmit to activate all.
        limit_order = self.buy(
            data=data,
            size=abs(main_order.size),
            price=limitprice,
            exectype=ExecType.Limit,
            parent=main_order,
            transmit=True,
            **limitargs,
        )

        return [main_order, stop_order, limit_order]

    # ------------------------------------------------------------------
    # Notification callbacks (override in subclass)
    # ------------------------------------------------------------------

    def notify_order(self, order: Order) -> None:
        """Called when an order's status changes.

        Override to handle order state transitions.
        """

    def notify_trade(self, trade: Any) -> None:
        """Called when a trade changes state.

        Override to handle trade events (open, close, etc.).
        """

    def notify_cashvalue(self, cash: float, value: float) -> None:
        """Called with portfolio cash and total value updates.

        Override to track portfolio state.
        """

    def notify_fund(
        self,
        cash: float,
        value: float,
        fundvalue: float,
        shares: float,
    ) -> None:
        """Called with fund-mode portfolio updates.

        Override for fund-mode tracking.
        """

    def notify_store(self, msg: Any, *args: Any, **kwargs: Any) -> None:
        """Called with messages from the store (live trading).

        Override for store message handling.
        """

    def notify_data(self, data: Any, status: Any, *args: Any, **kwargs: Any) -> None:
        """Called when a data feed status changes (live trading).

        Override for data feed status handling.
        """

    def notify_timer(self, timer: Any, when: Any, *args: Any, **kwargs: Any) -> None:
        """Called on timer events.

        Override for timer-based logic.
        """

    # ------------------------------------------------------------------
    # Position access
    # ------------------------------------------------------------------

    def getposition(self, data: Any = None) -> Position:
        """Return the Position object for the given data feed.

        Args:
            data: Data feed (default: first data feed).

        Returns:
            The Position object tracking holdings for this data.
        """
        if data is None:
            data = self.data
        return self.broker.getposition(data)

    @property
    def position(self) -> Position:
        """Shortcut for ``getposition(self.data)``."""
        return self.getposition(self.data)

    # ------------------------------------------------------------------
    # Writer support
    # ------------------------------------------------------------------

    def getwriterheaders(self) -> list[str]:
        """Return header strings for writer output.

        Returns column headers for all data feeds and their lines.
        """
        headers: list[str] = []
        for idx, data in enumerate(self.datas):
            name = getattr(data, "_name", None) or getattr(data, "name", f"data{idx}")
            line_names = getattr(data, "_line_names", None)
            if line_names is None:
                line_names = getattr(data, "line_names", ("close",))
            for lname in line_names:
                headers.append(f"{name}.{lname}")
        return headers

    def getwritervalues(self) -> list[Any]:
        """Return current values for writer output.

        Returns the current value of each line in each data feed.
        """
        values: list[Any] = []
        for data in self.datas:
            line_names = getattr(data, "_line_names", None)
            if line_names is None:
                line_names = getattr(data, "line_names", ("close",))
            for lname in line_names:
                line = getattr(data, lname, None)
                if line is not None:
                    if callable(getattr(line, "__getitem__", None)):
                        try:
                            values.append(line[0])
                        except (IndexError, TypeError, KeyError):
                            values.append(None)
                    elif isinstance(line, (int, float)):
                        values.append(line)
                    else:
                        values.append(None)
                else:
                    values.append(None)
        return values

    # ------------------------------------------------------------------
    # Child iterator registration (compatibility with MetaLineIterator)
    # ------------------------------------------------------------------

    def addindicator(self, indicator: Any) -> None:
        """Register a child indicator."""
        self._lineiterators[0].append(indicator)
        # Update min period from indicator.
        ind_mp = getattr(indicator, "_minperiod", 1)
        if ind_mp > self._minperiod:
            self._minperiod = ind_mp

    def addobserver(self, observer: Any) -> None:
        """Register a child observer."""
        self._lineiterators[2].append(observer)

    def addstrategy(self, strategy: Any) -> None:
        """Register a child strategy."""
        self._lineiterators[1].append(strategy)


class _ParamsAccessor:
    """Lightweight proxy providing attribute access to a params dict."""

    def __init__(self, params: dict[str, Any]) -> None:
        object.__setattr__(self, "_params", params)

    def __getattr__(self, name: str) -> Any:
        params = object.__getattribute__(self, "_params")
        try:
            return params[name]
        except KeyError:
            raise AttributeError(f"No parameter '{name}'")


def _get_close_price(data: Any) -> float | None:
    """Extract the current close price from a data feed."""
    close = getattr(data, "close", None)
    if close is None:
        return None
    if isinstance(close, (int, float)):
        return float(close)
    if callable(getattr(close, "__getitem__", None)):
        try:
            return float(close[0])
        except (IndexError, TypeError, KeyError):
            pass
    return None
