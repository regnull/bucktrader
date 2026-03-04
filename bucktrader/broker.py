"""Broker base interface and BackBroker implementation for bucktrader.

The broker receives and manages orders, simulates execution against market
data (backtesting), tracks positions, calculates commissions and margin,
and manages cash and credit.
"""

from __future__ import annotations

import collections
from datetime import datetime
from typing import Any

from bucktrader.comminfo import CommInfoBase, CommType
from bucktrader.order import ExecType, Order, OrderData, OrderStatus
from bucktrader.position import Position
from bucktrader.trade import Trade


# ── Broker Base Interface ─────────────────────────────────────────────────


class BrokerBase:
    """Abstract base class that all brokers must implement.

    Defines the contract for order submission, portfolio queries,
    lifecycle management, and notification delivery.
    """

    def __init__(self) -> None:
        self._notifications: collections.deque[Order] = collections.deque()

    # ── Order methods ─────────────────────────────────────────────────

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
        raise NotImplementedError

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
        raise NotImplementedError

    def cancel(self, order: Order) -> None:
        raise NotImplementedError

    # ── Portfolio methods ─────────────────────────────────────────────

    def getvalue(self, datas: list[Any] | None = None) -> float:
        raise NotImplementedError

    def getcash(self) -> float:
        raise NotImplementedError

    def getposition(self, data: Any) -> Position:
        raise NotImplementedError

    def get_fundshares(self) -> float:
        raise NotImplementedError

    def get_fundvalue(self) -> float:
        raise NotImplementedError

    # ── Lifecycle methods ─────────────────────────────────────────────

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def next(self) -> None:
        raise NotImplementedError

    # ── Notification methods ──────────────────────────────────────────

    def get_notification(self) -> Order | None:
        """Pop and return the next pending notification, or None."""
        if self._notifications:
            return self._notifications.popleft()
        return None

    def notify(self, order: Order) -> None:
        """Queue an order notification."""
        self._notifications.append(order)


# ── BackBroker (Backtesting Broker) ───────────────────────────────────────


class BackBroker(BrokerBase):
    """Simulated broker for backtesting.

    Matches orders against OHLCV bar data, applying slippage and
    volume constraints, and tracking positions and cash.

    Parameters:
        cash: Starting cash.
        checksubmit: Verify margin/cash before accepting orders.
        eosbar: Execute close orders on same bar.
        filler: Volume filler callable for partial fills.
        slip_perc: Slippage as a fraction of price.
        slip_fixed: Slippage as a fixed amount.
        slip_open: Apply slippage when executing at open price.
        slip_match: Clamp slipped price to bar high/low range.
        slip_limit: Apply slippage to limit orders.
        slip_out: Allow slippage outside bar range.
        coc: Cheat-on-close -- execute market orders at this bar's close.
        coo: Cheat-on-open -- execute market orders at current bar's open.
        int2pnl: Include interest charges in P&L.
        shortcash: Short sales generate cash inflow.
        fundstartval: Initial fund NAV per share.
        fundmode: Track portfolio as a fund.
        tradehistory: Record detailed trade history.
    """

    def __init__(
        self,
        cash: float = 10000.0,
        checksubmit: bool = True,
        eosbar: bool = False,
        filler: Any | None = None,
        slip_perc: float = 0.0,
        slip_fixed: float = 0.0,
        slip_open: bool = False,
        slip_match: bool = True,
        slip_limit: bool = True,
        slip_out: bool = False,
        coc: bool = False,
        coo: bool = False,
        int2pnl: bool = True,
        shortcash: bool = True,
        fundstartval: float = 100.0,
        fundmode: bool = False,
        tradehistory: bool = False,
    ):
        super().__init__()
        self.startingcash = cash
        self.cash = cash
        self.checksubmit = checksubmit
        self.eosbar = eosbar
        self.filler = filler
        self.slip_perc = slip_perc
        self.slip_fixed = slip_fixed
        self.slip_open = slip_open
        self.slip_match = slip_match
        self.slip_limit = slip_limit
        self.slip_out = slip_out
        self.coc = coc
        self.coo = coo
        self.int2pnl = int2pnl
        self.shortcash = shortcash
        self.fundstartval = fundstartval
        self.fundmode = fundmode
        self.tradehistory = tradehistory

        # Per-data positions: data -> Position.
        self._positions: dict[Any, Position] = {}

        # Commission info per data name, plus a default.
        self._comminfo: dict[str | None, CommInfoBase] = {
            None: CommInfoBase(stocklike=True)
        }

        # Order queues.
        self._pending: list[Order] = []  # Submitted, waiting to execute.
        self._waiting: list[Order] = []  # Waiting for transmit (bracket).

        # Trade tracking: (data, tradeid) -> list of open trades.
        self._trades: dict[tuple[Any, int], list[Trade]] = {}

        # Fund mode.
        self._fundshares: float = 0.0
        self._fundvalue: float = fundstartval

        # Owner reference (strategy).
        self._owner: Any = None

        # Current bar datetime (set externally or via data).
        self._dt: datetime | None = None

    # ── Configuration ─────────────────────────────────────────────────

    def setcommission(
        self,
        commission: float = 0.0,
        margin: float | None = None,
        mult: float = 1.0,
        commtype: CommType | None = None,
        percabs: bool = False,
        stocklike: bool = False,
        interest: float = 0.0,
        interest_long: bool = False,
        leverage: float = 1.0,
        automargin: bool = False,
        name: str | None = None,
    ) -> None:
        """Set the commission scheme, optionally per-instrument."""
        ci = CommInfoBase(
            commission=commission,
            mult=mult,
            margin=margin,
            commtype=commtype,
            stocklike=stocklike,
            percabs=percabs,
            interest=interest,
            interest_long=interest_long,
            leverage=leverage,
            automargin=automargin,
        )
        self._comminfo[name] = ci

    def addcommissioninfo(
        self, comminfo: CommInfoBase, name: str | None = None
    ) -> None:
        """Register a custom CommInfoBase instance."""
        self._comminfo[name] = comminfo

    def getcommissioninfo(self, data: Any = None) -> CommInfoBase:
        """Return the CommInfoBase for a data feed.

        Looks up by data name first, falls back to the default (None key).
        """
        name = getattr(data, "name", None) if data is not None else None
        return self._comminfo.get(name, self._comminfo[None])

    # ── Lifecycle ─────────────────────────────────────────────────────

    def start(self) -> None:
        self.cash = self.startingcash
        self._pending.clear()
        self._waiting.clear()
        if self.fundmode:
            self._fundshares = self.cash / self.fundstartval
            self._fundvalue = self.fundstartval

    def stop(self) -> None:
        pass

    # ── Portfolio queries ─────────────────────────────────────────────

    def getcash(self) -> float:
        return self.cash

    def setcash(self, cash: float) -> None:
        self.cash = cash

    def getposition(self, data: Any) -> Position:
        if data not in self._positions:
            self._positions[data] = Position()
        return self._positions[data]

    def getvalue(self, datas: list[Any] | None = None) -> float:
        """Return total portfolio value (cash + positions).

        Args:
            datas: If provided, only include these data feeds.
                   If None, include all positions.
        """
        value = self.cash
        positions = self._positions
        for data, pos in positions.items():
            if datas is not None and data not in datas:
                continue
            if pos.size == 0:
                continue
            comminfo = self.getcommissioninfo(data)
            price = _get_close(data)
            if comminfo.stocklike:
                value += pos.size * price * comminfo.mult
            else:
                # Futures: value is reflected through cash adjustments.
                # Position value is the margin held.
                value += abs(pos.size) * comminfo._get_margin(price)
        return value

    def get_fundshares(self) -> float:
        return self._fundshares

    def get_fundvalue(self) -> float:
        if not self.fundmode or self._fundshares == 0:
            return self._fundvalue
        return self.getvalue() / self._fundshares

    # ── Order submission ──────────────────────────────────────────────

    def buy(
        self,
        owner: Any = None,
        data: Any = None,
        size: float = 1.0,
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
        return self._submit_order(
            owner=owner,
            data=data,
            size=abs(size),
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

    def sell(
        self,
        owner: Any = None,
        data: Any = None,
        size: float = 1.0,
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
        return self._submit_order(
            owner=owner,
            data=data,
            size=-abs(size),
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

    def _submit_order(
        self,
        owner: Any,
        data: Any,
        size: float,
        price: float | None,
        plimit: float | None,
        exectype: ExecType,
        valid: Any,
        tradeid: int,
        oco: Order | None,
        trailamount: float | None,
        trailpercent: float | None,
        parent: Order | None,
        transmit: bool,
        **kwargs: Any,
    ) -> Order:
        """Create, submit, and enqueue an order."""
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

        # Initialize trailing stop price if applicable.
        if exectype in (ExecType.StopTrail, ExecType.StopTrailLimit):
            if price is not None:
                order._trail_stop_price = price

        # Link to parent (bracket orders).
        if parent is not None:
            parent.children.append(order)

        # Submit or wait.
        if transmit:
            self._transmit_order(order)
            # Also transmit any waiting children of the parent.
            if parent is not None:
                for child in parent.children:
                    if child is not order and child.status == OrderStatus.Created:
                        self._transmit_order(child)
            # Transmit waiting siblings.
            self._flush_waiting()
        else:
            # Hold in waiting queue until parent transmits.
            order.submit(dt=self._dt)
            self._waiting.append(order)

        return order

    def _transmit_order(self, order: Order) -> None:
        """Move an order from created/waiting to the pending queue."""
        order.submit(dt=self._dt)
        order.accept(dt=self._dt)
        self._pending.append(order)
        self.notify(order)

    def _flush_waiting(self) -> None:
        """Transmit all waiting orders whose parents have been transmitted."""
        still_waiting = []
        for order in self._waiting:
            parent = order.parent
            if parent is None or parent.status >= OrderStatus.Submitted:
                self._transmit_order(order)
            else:
                still_waiting.append(order)
        self._waiting = still_waiting

    def cancel(self, order: Order) -> None:
        """Cancel an order if it is still alive."""
        if not order.alive:
            return
        order.cancel()
        self.notify(order)
        self._handle_oco_cancel(order)

    # ── Main execution loop ───────────────────────────────────────────

    def next(self) -> None:
        """Process one bar: expire, execute, and settle orders.

        Call this once per bar with updated data feeds.

        Execution flow per spec section 3.2:
        1. Activate pending orders (waiting for transmit).
        2. Check submitted orders (verify margin if checksubmit=true).
        3. Deduct credit interest for open positions.
        4. For each pending order: check expiry, try execute, handle brackets.
        5. Adjust cash for futures mark-to-market.
        """
        # Step 1: Activate any waiting bracket children whose parent filled.
        self._activate_bracket_children()

        # Step 2: Check submitted orders for margin (already done at accept).
        if self.checksubmit:
            self._check_submitted_margin()

        # Step 3: Deduct credit interest.
        self._deduct_interest()

        # Step 4: Process pending orders.
        completed: list[Order] = []
        still_pending: list[Order] = []

        for order in self._pending:
            if not order.alive:
                completed.append(order)
                continue

            # Check expiration.
            if self._is_expired(order):
                order.expire()
                self.notify(order)
                self._handle_oco_cancel(order)
                completed.append(order)
                continue

            # Try to execute.
            executed = self._try_exec(order)
            if executed:
                if order.status == OrderStatus.Completed:
                    completed.append(order)
                    self._handle_bracket_fill(order)
                    self._handle_oco_fill(order)
                else:
                    still_pending.append(order)
            else:
                still_pending.append(order)

        self._pending = still_pending

        # Step 5: Futures mark-to-market cash adjustment.
        self._mark_to_market()

    def _activate_bracket_children(self) -> None:
        """Activate bracket children whose parent has been completed."""
        # Children are already in _pending from submission but only
        # become executable after parent fills. This is handled by
        # checking parent status in _try_exec.
        pass

    def _check_submitted_margin(self) -> None:
        """Reject orders that fail margin check."""
        rejects = []
        for order in self._pending:
            if order.status != OrderStatus.Accepted:
                continue
            comminfo = self.getcommissioninfo(order.data)
            price = order.price or _get_close(order.data)
            cost = comminfo.getoperationcost(abs(order.executed.remsize), price)
            if cost > self.cash and order.is_buy:
                order.margin()
                self.notify(order)
                rejects.append(order)
        self._pending = [o for o in self._pending if o not in rejects]

    def _deduct_interest(self) -> None:
        """Deduct daily credit interest for open positions."""
        for data, pos in self._positions.items():
            if pos.size == 0:
                continue
            comminfo = self.getcommissioninfo(data)
            interest = comminfo.get_credit_interest(data, pos, self._dt)
            if interest > 0:
                self.cash -= interest

    def _mark_to_market(self) -> None:
        """Adjust cash for futures-like positions (daily settlement)."""
        for data, pos in self._positions.items():
            if pos.size == 0:
                continue
            comminfo = self.getcommissioninfo(data)
            if comminfo.stocklike:
                continue
            current_price = _get_close(data)
            if pos.adjbase and current_price != pos.adjbase:
                adj = comminfo.cashadjust(pos.size, pos.adjbase, current_price)
                self.cash += adj
                pos.adjbase = current_price

    def _is_expired(self, order: Order) -> bool:
        """Check whether an order has expired based on its validity."""
        if order.valid is None:
            return False  # GTC

        if isinstance(order.valid, datetime):
            if self._dt is not None and self._dt > order.valid:
                return True
            return False

        if isinstance(order.valid, float) and order.valid == 0.0:
            # DAY order: expires at end of session.
            # For simplicity, expires on the next bar after creation.
            return self._dt is not None and self._dt != order.created.dt

        if isinstance(order.valid, int):
            # Valid for N bars -- would need bar counting.
            # Simplified: treat as non-expiring for now.
            return False

        return False

    # ── Order execution engine ────────────────────────────────────────

    def _try_exec(self, order: Order) -> bool:
        """Attempt to execute an order against the current bar.

        Returns True if any fill occurred, False otherwise.
        """
        # Bracket children should not execute until parent fills.
        if order.parent is not None:
            if order.parent.status != OrderStatus.Completed:
                return False

        data = order.data
        if data is None:
            return False

        exectype = order.exectype

        if exectype == ExecType.Market:
            return self._try_exec_market(order, data)
        elif exectype == ExecType.Close:
            return self._try_exec_close(order, data)
        elif exectype == ExecType.Limit:
            return self._try_exec_limit(order, data)
        elif exectype == ExecType.Stop:
            return self._try_exec_stop(order, data)
        elif exectype == ExecType.StopLimit:
            return self._try_exec_stoplimit(order, data)
        elif exectype == ExecType.StopTrail:
            return self._try_exec_stoptrail(order, data)
        elif exectype == ExecType.StopTrailLimit:
            return self._try_exec_stoptraillimit(order, data)
        elif exectype == ExecType.Historical:
            return self._try_exec_historical(order, data)

        return False

    def _try_exec_market(self, order: Order, data: Any) -> bool:
        """Execute a market order."""
        if self.coc:
            price = _get_close(data)
        elif self.coo:
            price = _get_open(data)
        else:
            price = _get_open(data)

        if price is None or price <= 0:
            return False

        price = self._apply_slippage(order, price, data)
        return self._fill(order, price, data)

    def _try_exec_close(self, order: Order, data: Any) -> bool:
        """Execute a close order at the bar's close price."""
        price = _get_close(data)
        if price is None or price <= 0:
            return False
        return self._fill(order, price, data)

    def _try_exec_limit(self, order: Order, data: Any) -> bool:
        """Execute a limit order if the limit price is reached."""
        limit_price = order.price
        if limit_price is None:
            return False

        high = _get_high(data)
        low = _get_low(data)
        open_price = _get_open(data)

        if order.is_buy:
            # Buy limit: triggers if bar.low <= limit_price.
            if low is not None and low <= limit_price:
                exec_price = min(limit_price, open_price) if open_price else limit_price
                if not self.slip_limit:
                    return self._fill(order, exec_price, data)
                exec_price = self._apply_slippage(order, exec_price, data)
                return self._fill(order, exec_price, data)
        else:
            # Sell limit: triggers if bar.high >= limit_price.
            if high is not None and high >= limit_price:
                exec_price = max(limit_price, open_price) if open_price else limit_price
                if not self.slip_limit:
                    return self._fill(order, exec_price, data)
                exec_price = self._apply_slippage(order, exec_price, data)
                return self._fill(order, exec_price, data)

        return False

    def _try_exec_stop(self, order: Order, data: Any) -> bool:
        """Execute a stop order if the stop price is reached."""
        stop_price = order.price
        if stop_price is None:
            return False

        high = _get_high(data)
        low = _get_low(data)
        open_price = _get_open(data)

        if order.is_buy:
            # Buy stop: triggers if bar.high >= stop_price.
            if high is not None and high >= stop_price:
                exec_price = (
                    max(stop_price, open_price) if open_price else stop_price
                )
                exec_price = self._apply_slippage(order, exec_price, data)
                return self._fill(order, exec_price, data)
        else:
            # Sell stop: triggers if bar.low <= stop_price.
            if low is not None and low <= stop_price:
                exec_price = (
                    min(stop_price, open_price) if open_price else stop_price
                )
                exec_price = self._apply_slippage(order, exec_price, data)
                return self._fill(order, exec_price, data)

        return False

    def _try_exec_stoplimit(self, order: Order, data: Any) -> bool:
        """Execute a stop-limit order (two phases).

        Phase 1: Stop triggers (same as stop logic).
        Phase 2: Limit order at pricelimit price.
        """
        # Phase 1: check if stop has been triggered.
        if not getattr(order, "_stop_triggered", False):
            stop_price = order.price
            if stop_price is None:
                return False

            high = _get_high(data)
            low = _get_low(data)

            triggered = False
            if order.is_buy:
                if high is not None and high >= stop_price:
                    triggered = True
            else:
                if low is not None and low <= stop_price:
                    triggered = True

            if triggered:
                order._stop_triggered = True
                # Fall through to phase 2 on same bar.
            else:
                return False

        # Phase 2: execute as limit at pricelimit.
        limit_price = order.pricelimit
        if limit_price is None:
            return False

        high = _get_high(data)
        low = _get_low(data)
        open_price = _get_open(data)

        if order.is_buy:
            if low is not None and low <= limit_price:
                exec_price = min(limit_price, open_price) if open_price else limit_price
                if self.slip_limit:
                    exec_price = self._apply_slippage(order, exec_price, data)
                return self._fill(order, exec_price, data)
        else:
            if high is not None and high >= limit_price:
                exec_price = max(limit_price, open_price) if open_price else limit_price
                if self.slip_limit:
                    exec_price = self._apply_slippage(order, exec_price, data)
                return self._fill(order, exec_price, data)

        return False

    def _try_exec_stoptrail(self, order: Order, data: Any) -> bool:
        """Execute a trailing stop order."""
        high = _get_high(data)
        low = _get_low(data)
        open_price = _get_open(data)

        if high is None or low is None:
            return False

        if order.is_buy:
            # Buy trailing stop (covering a short): trail below highs.
            # Trail price moves down with the market.
            if order.trailpercent is not None:
                trail_price = low + low * order.trailpercent
            elif order.trailamount is not None:
                trail_price = low + order.trailamount
            else:
                return False

            if order._trail_stop_price is None:
                order._trail_stop_price = trail_price
            else:
                order._trail_stop_price = min(order._trail_stop_price, trail_price)

            if high >= order._trail_stop_price:
                exec_price = (
                    max(order._trail_stop_price, open_price)
                    if open_price
                    else order._trail_stop_price
                )
                exec_price = self._apply_slippage(order, exec_price, data)
                return self._fill(order, exec_price, data)
        else:
            # Sell trailing stop (protecting a long): trail above lows.
            # Trail price moves up with the market.
            if order.trailpercent is not None:
                trail_price = high - high * order.trailpercent
            elif order.trailamount is not None:
                trail_price = high - order.trailamount
            else:
                return False

            if order._trail_stop_price is None:
                order._trail_stop_price = trail_price
            else:
                order._trail_stop_price = max(order._trail_stop_price, trail_price)

            if low <= order._trail_stop_price:
                exec_price = (
                    min(order._trail_stop_price, open_price)
                    if open_price
                    else order._trail_stop_price
                )
                exec_price = self._apply_slippage(order, exec_price, data)
                return self._fill(order, exec_price, data)

        return False

    def _try_exec_stoptraillimit(self, order: Order, data: Any) -> bool:
        """Execute a trailing stop-limit order.

        Phase 1: Trailing stop triggers.
        Phase 2: Limit order at pricelimit.
        """
        if not getattr(order, "_stop_triggered", False):
            high = _get_high(data)
            low = _get_low(data)
            if high is None or low is None:
                return False

            if order.is_buy:
                if order.trailpercent is not None:
                    trail_price = low + low * order.trailpercent
                elif order.trailamount is not None:
                    trail_price = low + order.trailamount
                else:
                    return False

                if order._trail_stop_price is None:
                    order._trail_stop_price = trail_price
                else:
                    order._trail_stop_price = min(
                        order._trail_stop_price, trail_price
                    )

                if high >= order._trail_stop_price:
                    order._stop_triggered = True
                else:
                    return False
            else:
                if order.trailpercent is not None:
                    trail_price = high - high * order.trailpercent
                elif order.trailamount is not None:
                    trail_price = high - order.trailamount
                else:
                    return False

                if order._trail_stop_price is None:
                    order._trail_stop_price = trail_price
                else:
                    order._trail_stop_price = max(
                        order._trail_stop_price, trail_price
                    )

                if low <= order._trail_stop_price:
                    order._stop_triggered = True
                else:
                    return False

        # Phase 2: limit execution at pricelimit.
        limit_price = order.pricelimit
        if limit_price is None:
            return False

        high = _get_high(data)
        low = _get_low(data)
        open_price = _get_open(data)

        if order.is_buy:
            if low is not None and low <= limit_price:
                exec_price = min(limit_price, open_price) if open_price else limit_price
                return self._fill(order, exec_price, data)
        else:
            if high is not None and high >= limit_price:
                exec_price = max(limit_price, open_price) if open_price else limit_price
                return self._fill(order, exec_price, data)

        return False

    def _try_exec_historical(self, order: Order, data: Any) -> bool:
        """Execute a historical order at the specified price."""
        price = order.price
        if price is None:
            return False
        return self._fill(order, price, data)

    # ── Fill logic ────────────────────────────────────────────────────

    def _fill(self, order: Order, price: float, data: Any) -> bool:
        """Fill an order (fully or partially via filler) at *price*.

        Returns True if any fill occurred.
        """
        remaining = order.executed.remsize
        fill_size = remaining  # Default: fill entire remaining.

        # Apply filler for partial fills.
        if self.filler is not None:
            max_fill = self.filler(order, price, 0)
            if order.is_buy:
                fill_size = min(abs(remaining), max_fill)
            else:
                fill_size = min(abs(remaining), max_fill)
                fill_size = -fill_size  # Keep sign.

            if abs(fill_size) < 1e-9:
                return False

            if order.is_buy:
                pass  # fill_size is already positive.
            # For sell orders, fill_size should be negative.

        if order.is_buy:
            fill_size = abs(fill_size)
        else:
            fill_size = -abs(fill_size)

        # Get commission info.
        comminfo = self.getcommissioninfo(data)

        # Update position.
        pos = self.getposition(data)
        opened, closed, pnl = pos.update(fill_size, price, dt=self._dt)

        # Calculate commission.
        comm = comminfo.getcommission(fill_size, price)

        # Calculate value.
        value = comminfo.getoperationcost(fill_size, price)

        # Update cash.
        if comminfo.stocklike:
            # Stocks: deduct full value for buys, credit for sells.
            self.cash -= fill_size * price * comminfo.mult
            self.cash -= comm
        else:
            # Futures: deduct margin for new exposure, return margin on close.
            margin_per_unit = comminfo._get_margin(price)
            if abs(opened) > 0:
                self.cash -= abs(opened) * margin_per_unit
            if abs(closed) > 0:
                old_price = pos.price if pos.size != 0 else price
                self.cash += abs(closed) * comminfo._get_margin(old_price)
                self.cash += pnl
            self.cash -= comm

        # Record execution on order.
        order.execute(
            dt=self._dt,
            size=fill_size,
            price=price,
            closed=closed,
            opened=opened,
            comm=comm,
            pnl=pnl,
            value=value,
        )

        # Update trade tracking.
        self._update_trades(order, fill_size, price, value, comm, pnl)

        # Notify.
        self.notify(order)

        return True

    def _update_trades(
        self,
        order: Order,
        size: float,
        price: float,
        value: float,
        comm: float,
        pnl: float,
    ) -> None:
        """Update trade tracking after a fill."""
        data = order.data
        tradeid = order.tradeid
        key = (data, tradeid)

        if key not in self._trades:
            self._trades[key] = []

        trades = self._trades[key]

        # Find an open trade to update, or create a new one.
        trade = None
        for t in trades:
            if t.isopen:
                trade = t
                break

        if trade is None:
            trade = Trade(
                data=data,
                tradeid=tradeid,
                historyon=self.tradehistory,
            )
            trades.append(trade)

        trade.update(
            order_ref=order.ref,
            size=size,
            price=price,
            value=value,
            commission=comm,
            pnl=pnl,
            dt=self._dt,
        )

        # If trade closed and there is leftover size (reversal),
        # open a new trade with the remainder.
        # (Handled naturally since position update already split it.)

    # ── Slippage ──────────────────────────────────────────────────────

    def _apply_slippage(
        self, order: Order, price: float, data: Any
    ) -> float:
        """Apply slippage to the execution price.

        Buys slip up (worse), sells slip down (worse).
        """
        if self.slip_perc == 0.0 and self.slip_fixed == 0.0:
            return price

        # Don't apply to open price unless slip_open is set.
        open_price = _get_open(data)
        if price == open_price and not self.slip_open:
            return price

        # Calculate slippage amount.
        if self.slip_perc > 0:
            slip = price * self.slip_perc
        else:
            slip = self.slip_fixed

        # Apply direction.
        if order.is_buy:
            slipped = price + slip
        else:
            slipped = price - slip

        # Clamp to bar range if slip_match is on.
        if self.slip_match and not self.slip_out:
            high = _get_high(data)
            low = _get_low(data)
            if high is not None and low is not None:
                if order.is_buy:
                    slipped = min(slipped, high)
                else:
                    slipped = max(slipped, low)

        return slipped

    # ── OCO handling ──────────────────────────────────────────────────

    def _handle_oco_fill(self, order: Order) -> None:
        """When an OCO order fills, cancel the linked order."""
        if order.oco is None:
            return
        linked = order.oco
        if linked.alive:
            self.cancel(linked)
        # Also cancel any order whose oco points to the filled order.
        for pending in list(self._pending):
            if pending.oco is order and pending.alive and pending is not linked:
                self.cancel(pending)

    def _handle_oco_cancel(self, order: Order) -> None:
        """When an OCO order is canceled/expired, cancel linked orders."""
        if order.oco is None:
            return
        linked = order.oco
        if linked.alive:
            self.cancel(linked)

    # ── Bracket handling ──────────────────────────────────────────────

    def _handle_bracket_fill(self, order: Order) -> None:
        """Handle bracket order logic when an order fills.

        - Parent fills: children become active (already in pending).
        - Child fills: cancel the sibling.
        """
        if order.parent is not None:
            # A child filled. Cancel siblings.
            parent = order.parent
            for child in parent.children:
                if child is not order and child.alive:
                    self.cancel(child)
        # If the parent itself filled, children are already in pending
        # and will become executable on the next bar (parent check passes).

    def get_orders_open(self) -> list[Order]:
        """Return a copy of the pending orders list."""
        return list(self._pending)

    def get_trades(
        self, data: Any = None, tradeid: int | None = None
    ) -> list[Trade]:
        """Return trades, optionally filtered by data and/or tradeid."""
        result = []
        for (d, tid), trades in self._trades.items():
            if data is not None and d is not data:
                continue
            if tradeid is not None and tid != tradeid:
                continue
            result.extend(trades)
        return result

    def __repr__(self) -> str:
        return (
            f"BackBroker(cash={self.cash:.2f}, "
            f"pending={len(self._pending)}, "
            f"positions={len(self._positions)})"
        )


# ── Data access helpers ──────────────────────────────────────────────────
#
# These helpers safely extract OHLCV fields from data objects.
# Data objects may be simple namespace objects, dicts, or Line-based feeds.
# We support both attribute access (data.close) and indexable access
# (data.close[0]).


def _get_field(data: Any, field: str) -> float | None:
    """Extract a scalar price field from a data object."""
    if data is None:
        return None
    attr = getattr(data, field, None)
    if attr is None:
        return None
    # If it is directly a number, return it.
    if isinstance(attr, (int, float)):
        return float(attr)
    # If it is indexable (list, array, Line), get current value.
    if callable(getattr(attr, "__getitem__", None)):
        try:
            return float(attr[0])
        except (IndexError, TypeError, KeyError):
            pass
    # If callable, call it.
    if callable(attr):
        try:
            return float(attr())
        except (TypeError, ValueError):
            pass
    return None


def _get_open(data: Any) -> float | None:
    return _get_field(data, "open")


def _get_high(data: Any) -> float | None:
    return _get_field(data, "high")


def _get_low(data: Any) -> float | None:
    return _get_field(data, "low")


def _get_close(data: Any) -> float | None:
    return _get_field(data, "close")


def _get_volume(data: Any) -> float | None:
    return _get_field(data, "volume")
