"""Cortex -- top-level orchestrator for the bucktrader framework.

Cortex manages the registry of data feeds, strategies, brokers, observers,
analyzers, and writers. It controls execution mode (preload, runonce, live,
optimization) and implements the main event loop.

Usage::

    cortex = Cortex()
    cortex.adddata(data_feed)
    cortex.addstrategy(MyStrategy, period=20)
    results = cortex.run()
"""

from __future__ import annotations

import itertools
import math
from datetime import time, timedelta
from typing import Any, Optional, Sequence

from bucktrader.broker import BackBroker, BrokerBase
from bucktrader.dataseries import num2date
from bucktrader.filters.replay import Replayer
from bucktrader.filters.resample import Resampler
from bucktrader.timer import SESSION_END, SESSION_START, Timer

# Default initial cash for the backtesting broker.
_DEFAULT_CASH = 10_000.0


# -- OptReturn -----------------------------------------------------------------


class OptReturn:
    """Lightweight result object returned during optimization runs.

    Instead of returning the full strategy object (with all line data,
    indicator state, and order history), OptReturn carries only the
    parameter combination and computed analyzer results.

    Attributes:
        params: Strategy parameter values for this run.
        analyzers: Map of analyzer name to analysis results.
    """

    def __init__(
        self,
        params: dict[str, Any],
        analyzers: dict[str, Any],
    ) -> None:
        self.params = dict(params)
        self.analyzers = dict(analyzers)

    def __repr__(self) -> str:
        return f"OptReturn(params={self.params}, analyzers={list(self.analyzers)})"


# -- Strategy Registration Entry -----------------------------------------------


class _StratEntry:
    """Internal record for a registered strategy class."""

    __slots__ = ("cls", "args", "kwargs", "is_opt")

    def __init__(
        self,
        cls: type,
        args: tuple,
        kwargs: dict[str, Any],
        is_opt: bool = False,
    ) -> None:
        self.cls = cls
        self.args = args
        self.kwargs = kwargs
        self.is_opt = is_opt


# -- Cortex Engine -------------------------------------------------------------


class Cortex:
    """Top-level orchestrator.

    Manages the registry of data feeds, strategies, brokers, observers,
    analyzers, and writers. Controls execution mode and implements
    the main event loop.

    Parameters:
        preload: Load all data into memory before running.
        runonce: Run indicators in vectorized mode (requires preload).
        live: Force live-trading mode (disables preload and runonce).
        maxcpus: Max CPU cores for optimization (None = all, 1 = sequential).
        stdstats: Add default observers (Broker, Trades, BuySell).
        exactbars: Memory saving level (False/0, 1, -1, -2).
        optdatas: Preload data once for all optimization runs.
        optreturn: Return lightweight results during optimization.
        objcache: Cache identical indicator objects.
        writer: Add default writer.
        tradehistory: Log trade history events.
        oldsync: Use old data synchronization (data0 as master).
        tz: Global timezone for strategies.
        cheat_on_open: Call ``next_open()`` before broker processes orders.
        broker_coo: Auto-configure broker for cheat-on-open.
        quicknotify: Deliver broker notifications immediately.
    """

    def __init__(
        self,
        preload: bool = True,
        runonce: bool = True,
        live: bool = False,
        maxcpus: Optional[int] = None,
        stdstats: bool = True,
        exactbars: bool | int = False,
        optdatas: bool = True,
        optreturn: bool = True,
        objcache: bool = False,
        writer: bool = False,
        tradehistory: bool = False,
        oldsync: bool = False,
        tz: Optional[Any] = None,
        cheat_on_open: bool = False,
        broker_coo: bool = True,
        quicknotify: bool = False,
    ) -> None:
        # Configuration parameters.
        self.p_preload = preload
        self.p_runonce = runonce
        self.p_live = live
        self.p_maxcpus = maxcpus
        self.p_stdstats = stdstats
        self.p_exactbars = exactbars
        self.p_optdatas = optdatas
        self.p_optreturn = optreturn
        self.p_objcache = objcache
        self.p_writer = writer
        self.p_tradehistory = tradehistory
        self.p_oldsync = oldsync
        self.p_tz = tz
        self.p_cheat_on_open = cheat_on_open
        self.p_broker_coo = broker_coo
        self.p_quicknotify = quicknotify

        # Registries.
        self._datas: list[Any] = []
        self._strats: list[_StratEntry] = []
        self._indicators: list[tuple[type, tuple, dict[str, Any]]] = []
        self._observers: list[tuple[type, tuple, dict[str, Any]]] = []
        self._analyzers: list[tuple[type, tuple, dict[str, Any]]] = []
        self._writers: list[tuple[type, tuple, dict[str, Any]]] = []
        self._sizers: list[tuple[type, tuple, dict[str, Any]]] = []
        self._sizers_byidx: dict[int, tuple[type, tuple, dict[str, Any]]] = {}
        self._timers: list[Timer] = []
        self._calendar: Any = None

        # Default broker.
        self._broker: BrokerBase = BackBroker(cash=_DEFAULT_CASH)

        # Results populated after run().
        self._results: list[Any] = []
        self._writer_instances: list[Any] = []

        # Stores (for live trading).
        self._stores: list[Any] = []

    # -- Data Feed Registration ------------------------------------------------

    def adddata(self, data: Any, name: Optional[str] = None) -> Any:
        """Register a data feed.

        If the data reports itself as live, Cortex switches to live mode.

        Args:
            data: A data feed instance.
            name: Optional name to assign to the feed.

        Returns:
            The data feed.
        """
        if name is not None:
            data.p_name = name
        self._datas.append(data)

        # Auto-detect live data.
        if hasattr(data, "islive") and data.islive():
            self.p_live = True

        return data

    def resampledata(
        self,
        data: Any,
        timeframe: Any = None,
        compression: int = 1,
        **kwargs: Any,
    ) -> Any:
        """Register a data feed with a Resampler filter attached.

        Args:
            data: Source data feed.
            timeframe: Target timeframe for resampling.
            compression: Compression factor.
            **kwargs: Additional keyword arguments for Resampler.

        Returns:
            The data feed.
        """
        if timeframe is None:
            from bucktrader.dataseries import TimeFrame
            timeframe = TimeFrame.Days

        resampler = Resampler(data, timeframe=timeframe, compression=compression)
        data._filters.append(resampler)
        return self.adddata(data, **kwargs)

    def replaydata(
        self,
        data: Any,
        timeframe: Any = None,
        compression: int = 1,
        **kwargs: Any,
    ) -> Any:
        """Register a data feed with a Replayer filter attached.

        Args:
            data: Source data feed.
            timeframe: Target timeframe for replaying.
            compression: Compression factor.
            **kwargs: Additional keyword arguments for Replayer.

        Returns:
            The data feed.
        """
        if timeframe is None:
            from bucktrader.dataseries import TimeFrame
            timeframe = TimeFrame.Days

        replayer = Replayer(data, timeframe=timeframe, compression=compression)
        data._filters.append(replayer)
        return self.adddata(data, **kwargs)

    # -- Strategy Registration -------------------------------------------------

    def addstrategy(self, cls: type, *args: Any, **kwargs: Any) -> int:
        """Register a strategy class with fixed parameters.

        Multiple strategies can be added; each runs independently.

        Args:
            cls: Strategy class.
            *args: Positional arguments for strategy constructor.
            **kwargs: Keyword arguments for strategy constructor.

        Returns:
            Index of the registered strategy.
        """
        entry = _StratEntry(cls, args, kwargs, is_opt=False)
        self._strats.append(entry)
        return len(self._strats) - 1

    def optstrategy(self, cls: type, *args: Any, **kwargs: Any) -> int:
        """Register a strategy class for parameter optimization.

        Keyword arguments with iterable values define the parameter grid.
        Cortex generates the cartesian product of all parameter combinations.

        Args:
            cls: Strategy class.
            *args: Positional arguments for strategy constructor.
            **kwargs: Keyword arguments -- iterables define the search grid.

        Returns:
            Index of the registered strategy.
        """
        entry = _StratEntry(cls, args, kwargs, is_opt=True)
        self._strats.append(entry)
        return len(self._strats) - 1

    # -- Component Registration ------------------------------------------------

    def addindicator(self, cls: type, *args: Any, **kwargs: Any) -> None:
        """Register an indicator to be added to ALL strategies."""
        self._indicators.append((cls, args, kwargs))

    def addobserver(
        self,
        cls: type,
        *args: Any,
        per_data: bool = False,
        **kwargs: Any,
    ) -> None:
        """Register an observer for all strategies.

        Args:
            cls: Observer class.
            per_data: If True, create one instance per data feed.
        """
        kwargs["_per_data"] = per_data
        self._observers.append((cls, args, kwargs))

    def addobservermulti(self, cls: type, *args: Any, **kwargs: Any) -> None:
        """Register an observer with per_data=True (one instance per feed)."""
        self.addobserver(cls, *args, per_data=True, **kwargs)

    def addanalyzer(self, cls: type, *args: Any, **kwargs: Any) -> None:
        """Register a performance analyzer for all strategies."""
        self._analyzers.append((cls, args, kwargs))

    def addsizer(self, cls: type, *args: Any, **kwargs: Any) -> None:
        """Set the default position sizer for all strategies."""
        self._sizers = [(cls, args, kwargs)]

    def addsizer_byidx(
        self, idx: int, cls: type, *args: Any, **kwargs: Any
    ) -> None:
        """Set a sizer for a specific strategy by index."""
        self._sizers_byidx[idx] = (cls, args, kwargs)

    def addwriter(self, cls: type, *args: Any, **kwargs: Any) -> None:
        """Register an output writer."""
        self._writers.append((cls, args, kwargs))

    def addcalendar(self, calendar: Any) -> None:
        """Set a trading calendar.

        Accepts a TradingCalendarBase instance, a string (exchange name),
        or a market calendar instance.
        """
        self._calendar = calendar

    def addstore(self, store: Any) -> None:
        """Register a live store integration."""
        if store not in self._stores:
            self._stores.append(store)

    def add_timer(
        self,
        when: time = SESSION_START,
        offset: timedelta = timedelta(0),
        repeat: timedelta = timedelta(0),
        weekdays: Optional[Sequence[int]] = None,
        weekcarry: bool = True,
        monthdays: Optional[Sequence[int]] = None,
        monthcarry: bool = True,
        allow: Optional[Any] = None,
        tzdata: Any = None,
        strats: bool = False,
        cheat: bool = False,
        *args: Any,
        **kwargs: Any,
    ) -> Timer:
        """Schedule a recurring timer callback.

        Returns:
            The created Timer instance.
        """
        timer = Timer(
            when=when,
            offset=offset,
            repeat=repeat,
            weekdays=weekdays,
            weekcarry=weekcarry,
            monthdays=monthdays,
            monthcarry=monthcarry,
            allow=allow,
            tzdata=tzdata,
            cheat=cheat,
            strats=strats,
            *args,
            **kwargs,
        )
        self._timers.append(timer)
        return timer

    # -- Broker Management -----------------------------------------------------

    def setbroker(self, broker: BrokerBase) -> None:
        """Replace the default broker with a custom one."""
        self._broker = broker

    def getbroker(self) -> BrokerBase:
        """Return the current broker."""
        return self._broker

    @property
    def broker(self) -> BrokerBase:
        """Get the current broker."""
        return self._broker

    @broker.setter
    def broker(self, broker: BrokerBase) -> None:
        """Set the current broker."""
        self._broker = broker

    # -- Execution: run() ------------------------------------------------------

    def run(self, **kwargs: Any) -> list[Any]:
        """Main entry point. Run all registered strategies against data.

        Returns a list of strategy instances (or OptReturn objects
        during optimization).

        Args:
            **kwargs: Runtime parameter overrides.
        """
        # Step 1: Apply runtime parameter overrides.
        self._apply_overrides(kwargs)

        # Step 2: Determine execution mode.
        if self.p_live:
            self.p_preload = False
            self.p_runonce = False

        if self.p_exactbars:
            self.p_runonce = False
            self.p_preload = False

        # runonce requires preload.
        if self.p_runonce and not self.p_preload:
            self.p_runonce = False

        # Step 3: Check for optimization.
        has_opt = any(s.is_opt for s in self._strats)

        if has_opt:
            results = self._run_optimization()
        else:
            # Single run.
            iterstrat = self._build_iterstrat()
            results = self.runstrategies(iterstrat)
            self._results = results

        return results

    # -- Execution: runstrategies() --------------------------------------------

    def runstrategies(
        self,
        iterstrat: list[tuple[type, tuple, dict[str, Any]]],
        predata: bool = False,
    ) -> list[Any]:
        """Set up and run strategies for one parameter combination.

        Args:
            iterstrat: List of (strategy_class, args, kwargs) for this run.
            predata: If True, data has already been preloaded.

        Returns:
            List of strategy instances (or OptReturn if optreturn is set).
        """
        # Step 1: Initialize broker, data feeds, stores.
        self._broker.start()

        if hasattr(self._broker, "tradehistory"):
            self._broker.tradehistory = self.p_tradehistory

        for data in self._datas:
            data.start()
            store = getattr(data, "_store", None)
            if store is not None and store not in self._stores:
                self._stores.append(store)

        broker_store = getattr(self._broker, "_store", None)
        if broker_store is not None and broker_store not in self._stores:
            self._stores.append(broker_store)

        for store in self._stores:
            if hasattr(store, "start"):
                try:
                    store.start()
                except TypeError:
                    store.start(data=None, broker=None)

        # Step 2: Preload data if configured.
        if self.p_preload and not predata:
            for data in self._datas:
                data.preload()

        # Step 3: Instantiate strategies.
        runstrats: list[Any] = []
        for strat_cls, strat_args, strat_kwargs in iterstrat:
            strat = strat_cls(*strat_args, **strat_kwargs)

            # Wire up the strategy's environment.
            strat.env = self
            strat.cortex = self
            strat.broker = self._broker
            strat.datas = list(self._datas)
            if self._datas:
                strat.data = self._datas[0]

            # Set up named data references.
            for idx, d in enumerate(self._datas):
                setattr(strat, f"data{idx}", d)
                dname = getattr(d, "p_name", "") or ""
                if dname:
                    if not hasattr(strat, "dnames"):
                        strat.dnames = {}
                    strat.dnames[dname] = d

            # Add indicators registered via addindicator.
            for ind_cls, ind_args, ind_kwargs in self._indicators:
                try:
                    ind = ind_cls(strat, *ind_args, **ind_kwargs)
                    if hasattr(strat, "_lineiterators"):
                        from bucktrader.metabase import IndType
                        strat._lineiterators.setdefault(IndType, []).append(ind)
                except Exception:
                    pass  # Indicator construction may fail if Strategy is not ready.

            # Add observers (including default stdstats observers if enabled).
            observer_specs = list(self._observers)
            if self.p_stdstats:
                from bucktrader.observers import Broker as BrokerObserver
                from bucktrader.observers import BuySell, Trades
                existing = {spec[0] for spec in observer_specs}
                for std_cls in (BrokerObserver, BuySell, Trades):
                    if std_cls not in existing:
                        observer_specs.append((std_cls, (), {}))

            for obs_cls, obs_args, obs_kwargs in observer_specs:
                try:
                    kw = dict(obs_kwargs)
                    kw.pop("_per_data", None)
                    obs = obs_cls(strat, *obs_args, **kw)
                    if hasattr(strat, "_lineiterators"):
                        from bucktrader.metabase import ObsType
                        strat._lineiterators.setdefault(ObsType, []).append(obs)
                except Exception:
                    pass

            # Add analyzers.
            strat._analyzers = []
            for ana_cls, ana_args, ana_kwargs in self._analyzers:
                try:
                    ana = ana_cls(strat, *ana_args, **ana_kwargs)
                    strat._analyzers.append(ana)
                except Exception:
                    pass

            # Start the strategy.
            strat.start()
            for obs in getattr(strat, "_lineiterators", {}).get(2, []):
                if hasattr(obs, "start"):
                    obs.start()
            for ana in strat._analyzers:
                if hasattr(ana, "start"):
                    ana.start()

            runstrats.append(strat)

        # Step 4: Initialize writers.
        self._setup_writers(runstrats)

        # Step 5: Configure cheat-on-open broker mode.
        if self.p_cheat_on_open and self.p_broker_coo:
            if hasattr(self._broker, "coo"):
                self._broker.coo = True

        # Step 6: Choose execution path.
        if self.p_runonce and self.p_preload:
            self._runonce(runstrats)
        else:
            self._runnext(runstrats)

        # Step 7: Stop writers.
        self._stop_writers()

        # Step 8: Stop strategies.
        for strat in runstrats:
            for ana in getattr(strat, "_analyzers", []):
                if hasattr(ana, "stop"):
                    ana.stop()
            for obs in getattr(strat, "_lineiterators", {}).get(2, []):
                if hasattr(obs, "stop"):
                    obs.stop()
            strat.stop()

        # Stop data feeds and broker.
        for data in self._datas:
            data.stop()
        self._broker.stop()

        # Step 9: Wrap in OptReturn if optimization.
        if self.p_optreturn and any(s.is_opt for s in self._strats):
            return self._wrap_optreturn(runstrats)

        return runstrats

    # -- Vectorized Execution Path ---------------------------------------------

    def _runonce(self, runstrats: list[Any]) -> None:
        """Vectorized execution: preloaded data, indicator _once(), bar loop.

        All data must already be preloaded.
        """
        # Step 1: Call _once() on each strategy to compute indicators vectorized.
        for strat in runstrats:
            if hasattr(strat, "_once"):
                strat._once()

        # Step 2: Determine the total number of bars.
        if not self._datas:
            return

        total_bars = max(len(d) for d in self._datas)
        if total_bars == 0:
            return

        # Step 3: Reset all data feed pointers to home position.
        for data in self._datas:
            data.home()

        # Step 4: Iterate through each bar.
        for bar_idx in range(total_bars):
            # Find the minimum datetime across all data feeds that have
            # data at this bar index.
            min_dt = float("inf")
            for data in self._datas:
                if bar_idx < len(data):
                    dt_val = data.datetime.get_absolute(bar_idx)
                    if not math.isnan(dt_val) and dt_val < min_dt:
                        min_dt = dt_val

            if min_dt == float("inf"):
                continue

            # Advance data feeds whose datetime matches the minimum.
            for data in self._datas:
                if bar_idx < len(data):
                    dt_val = data.datetime.get_absolute(bar_idx)
                    if not math.isnan(dt_val) and dt_val <= min_dt:
                        data.advance()

            # Check cheat-on-open timers.
            if self.p_cheat_on_open:
                self._check_timers(runstrats, min_dt, cheat=True)

            # Process broker bar.
            self._broker.next()

            # Deliver broker notifications.
            self._brokernotify(runstrats)

            # Notify strategies of cash/value.
            self._notify_cashvalue(runstrats)

            # Call strategy _oncepost for this bar.
            for strat in runstrats:
                if hasattr(strat, "_oncepost"):
                    strat._oncepost(min_dt)
                self._run_components(strat)

            # Emit writer row for this bar.
            self._writers_next(runstrats)

            # Check regular timers.
            self._check_timers(runstrats, min_dt, cheat=False)

    # -- Event-Driven Execution Path -------------------------------------------

    def _runnext(self, runstrats: list[Any]) -> None:
        """Event-driven execution: load one bar at a time."""
        while True:
            # Notify stores of new tick.
            for store in self._stores:
                if hasattr(store, "next"):
                    store.next()

            # Deliver store/data notifications.
            self._storenotify(runstrats)

            # Load the next bar from each data feed.
            any_data = False
            datas_with_data = []
            for data in self._datas:
                ret = data.load()
                if ret:
                    any_data = True
                    datas_with_data.append(data)
                    # Check if data is live.
                    if hasattr(data, "islive") and data.islive():
                        self.p_live = True

            if not any_data:
                break

            # Synchronize data feeds: find the minimum datetime.
            min_dt = float("inf")
            for data in datas_with_data:
                dt_val = data.datetime[0]
                if not math.isnan(dt_val) and dt_val < min_dt:
                    min_dt = dt_val

            if min_dt == float("inf"):
                continue

            # For multi-data sync with oldsync: use data0 as master.
            if self.p_oldsync and self._datas:
                master = self._datas[0]
                master_dt = master.datetime[0]
                if not math.isnan(master_dt):
                    min_dt = master_dt

            # Set broker datetime.
            if hasattr(self._broker, "_dt"):
                dt_obj = num2date(min_dt)
                self._broker._dt = dt_obj

            # Check cheat-on-open timers.
            if self.p_cheat_on_open:
                self._check_timers(runstrats, min_dt, cheat=True)

                # Call next_open on strategies in cheat mode.
                for strat in runstrats:
                    if hasattr(strat, "next_open"):
                        strat.next_open()

            # Process broker bar.
            self._broker.next()

            # Deliver broker notifications.
            self._brokernotify(runstrats)

            # Notify strategies of cash/value.
            self._notify_cashvalue(runstrats)

            # Call strategy _next for each strategy.
            for strat in runstrats:
                if hasattr(strat, "_next"):
                    strat._next()
                self._run_components(strat)

            # Emit writer row for this bar.
            self._writers_next(runstrats)

            # Check regular timers.
            self._check_timers(runstrats, min_dt, cheat=False)

            # Deliver store/data notifications after bar processing too.
            self._storenotify(runstrats)

    # -- Broker Notifications --------------------------------------------------

    def _brokernotify(self, runstrats: list[Any]) -> None:
        """Deliver pending broker notifications to strategies.

        Pops all pending notifications from the broker and delivers
        them to the appropriate strategy via notify_order() and
        notify_trade().
        """
        while True:
            order = self._broker.get_notification()
            if order is None:
                break

            # Find the owning strategy -- for now, deliver to all strategies.
            for strat in runstrats:
                if hasattr(strat, "notify_order"):
                    strat.notify_order(order)
                for obs in getattr(strat, "_lineiterators", {}).get(2, []):
                    if hasattr(obs, "notify_order"):
                        obs.notify_order(order)
                for ana in getattr(strat, "_analyzers", []):
                    if hasattr(ana, "notify_order"):
                        ana.notify_order(order)

                # Check for affected trades.
                if hasattr(strat, "notify_trade") and hasattr(
                    self._broker, "get_trades"
                ):
                    trades = self._broker.get_trades(data=order.data)
                    for trade in trades:
                        if trade.justopened or trade.isclosed:
                            strat.notify_trade(trade)
                            for obs in getattr(strat, "_lineiterators", {}).get(2, []):
                                if hasattr(obs, "notify_trade"):
                                    obs.notify_trade(trade)
                            for ana in getattr(strat, "_analyzers", []):
                                if hasattr(ana, "notify_trade"):
                                    ana.notify_trade(trade)

    def _notify_cashvalue(self, runstrats: list[Any]) -> None:
        """Notify strategies of current cash and portfolio value."""
        cash = self._broker.getcash()
        value = self._broker.getvalue()

        for strat in runstrats:
            if hasattr(strat, "notify_cashvalue"):
                strat.notify_cashvalue(cash, value)
            for ana in getattr(strat, "_analyzers", []):
                if hasattr(ana, "notify_cashvalue"):
                    ana.notify_cashvalue(cash, value)

            if hasattr(strat, "notify_fund"):
                fundvalue = self._broker.get_fundvalue()
                fundshares = self._broker.get_fundshares()
                strat.notify_fund(cash, value, fundvalue, fundshares)
            for ana in getattr(strat, "_analyzers", []):
                if hasattr(ana, "notify_fund"):
                    ana.notify_fund(cash, value, fundvalue, fundshares)

    # -- Timer System ----------------------------------------------------------

    def _check_timers(
        self,
        runstrats: list[Any],
        dt_num: float,
        cheat: bool,
    ) -> None:
        """Check all timers and fire those that match.

        Args:
            runstrats: Active strategy instances.
            dt_num: Current bar datetime (float).
            cheat: If True, only check cheat timers; if False, only regular.
        """
        for timer in self._timers:
            if timer.cheat != cheat:
                continue

            if timer.check(dt_num):
                for strat in runstrats:
                    if hasattr(strat, "notify_timer"):
                        strat.notify_timer(
                            timer,
                            num2date(dt_num),
                            *timer.args,
                            **timer.kwargs,
                        )

    def _storenotify(self, runstrats: list[Any]) -> None:
        """Deliver store notifications and live data status changes."""
        for store in self._stores:
            if hasattr(store, "get_notifications"):
                for msg, args, kwargs in store.get_notifications():
                    for strat in runstrats:
                        if hasattr(strat, "notify_store"):
                            strat.notify_store(msg, *args, **kwargs)

        for data in self._datas:
            if hasattr(data, "get_notifications"):
                for status, args, kwargs in data.get_notifications():
                    for strat in runstrats:
                        if hasattr(strat, "notify_data"):
                            strat.notify_data(data, status, *args, **kwargs)

    def _run_components(self, strat: Any) -> None:
        """Advance observer/analyzer components for one bar."""
        for obs in getattr(strat, "_lineiterators", {}).get(2, []):
            if hasattr(obs, "forward"):
                obs.forward()
            if hasattr(obs, "next"):
                obs.next()
        for ana in getattr(strat, "_analyzers", []):
            if hasattr(ana, "next"):
                ana.next()

    # -- Writer Lifecycle -------------------------------------------------------

    def _setup_writers(self, runstrats: list[Any]) -> None:
        """Instantiate and start configured writers."""
        writer_specs = list(self._writers)
        if self.p_writer and not writer_specs:
            from bucktrader.writer import WriterFile

            writer_specs.append((WriterFile, (), {}))

        self._writer_instances = []
        for writer_cls, writer_args, writer_kwargs in writer_specs:
            try:
                writer = writer_cls(*writer_args, **writer_kwargs)
                if hasattr(writer, "start"):
                    writer.start()
                if runstrats and hasattr(writer, "addheaders"):
                    headers = runstrats[0].getwriterheaders()
                    writer.addheaders(headers)
                self._writer_instances.append(writer)
            except Exception:
                continue

    def _writers_next(self, runstrats: list[Any]) -> None:
        """Push current bar values into all active writers."""
        if not self._writer_instances or not runstrats:
            return
        values = runstrats[0].getwritervalues()
        for writer in self._writer_instances:
            if hasattr(writer, "next"):
                writer.next(values)

    def _stop_writers(self) -> None:
        """Stop and clear writer instances."""
        for writer in self._writer_instances:
            if hasattr(writer, "stop"):
                writer.stop()
        self._writer_instances = []

    # -- Optimization ----------------------------------------------------------

    def _run_optimization(self) -> list[Any]:
        """Generate parameter combos and run optimization.

        Currently implements sequential execution only.
        """
        all_results: list[Any] = []

        for entry in self._strats:
            if not entry.is_opt:
                continue

            combos = self._generate_combos(entry)

            for combo in combos:
                merged_kwargs = dict(entry.kwargs)
                merged_kwargs.update(combo)

                iterstrat = [(entry.cls, entry.args, merged_kwargs)]

                results = self.runstrategies(iterstrat)
                all_results.extend(results)

        return all_results

    def _generate_combos(
        self, entry: _StratEntry
    ) -> list[dict[str, Any]]:
        """Generate the cartesian product of all iterable kwargs.

        Non-iterable kwargs are treated as fixed values.
        """
        opt_keys: list[str] = []
        opt_values: list[list[Any]] = []

        for key, val in entry.kwargs.items():
            if isinstance(val, (list, tuple, range)):
                opt_keys.append(key)
                opt_values.append(list(val))

        if not opt_keys:
            return [{}]

        combos = []
        for combo_tuple in itertools.product(*opt_values):
            combo = dict(zip(opt_keys, combo_tuple))
            combos.append(combo)

        return combos

    def _wrap_optreturn(
        self, runstrats: list[Any]
    ) -> list[OptReturn]:
        """Wrap strategy instances in lightweight OptReturn objects."""
        results = []
        for strat in runstrats:
            params = {}
            if hasattr(strat, "params"):
                p = strat.params
                if hasattr(p, "getitems"):
                    params = dict(p.getitems())
                elif hasattr(p, "__dict__"):
                    params = dict(p.__dict__)
            elif hasattr(strat, "_params"):
                params = dict(strat._params)

            analyzers = {}
            for ana in getattr(strat, "_analyzers", []):
                name = type(ana).__name__
                if hasattr(ana, "get_analysis"):
                    analyzers[name] = ana.get_analysis()

            results.append(OptReturn(params=params, analyzers=analyzers))

        return results

    # -- Internal Helpers ------------------------------------------------------

    def _apply_overrides(self, kwargs: dict[str, Any]) -> None:
        """Apply runtime parameter overrides from kwargs."""
        param_map = {
            "preload": "p_preload",
            "runonce": "p_runonce",
            "live": "p_live",
            "maxcpus": "p_maxcpus",
            "stdstats": "p_stdstats",
            "exactbars": "p_exactbars",
            "optdatas": "p_optdatas",
            "optreturn": "p_optreturn",
            "objcache": "p_objcache",
            "writer": "p_writer",
            "tradehistory": "p_tradehistory",
            "oldsync": "p_oldsync",
            "tz": "p_tz",
            "cheat_on_open": "p_cheat_on_open",
            "broker_coo": "p_broker_coo",
            "quicknotify": "p_quicknotify",
        }

        for key, attr in param_map.items():
            if key in kwargs:
                setattr(self, attr, kwargs[key])

    def _build_iterstrat(
        self,
    ) -> list[tuple[type, tuple, dict[str, Any]]]:
        """Build the strategy iteration list for a non-optimization run."""
        result = []
        for entry in self._strats:
            result.append((entry.cls, entry.args, dict(entry.kwargs)))
        return result

    # -- Plotting --------------------------------------------------------------

    def plot(
        self,
        plotter: Any = None,
        numfigs: int = 1,
        iplot: bool = True,
        start: int | None = None,
        end: int | None = None,
        width: int = 16,
        height: int = 9,
        dpi: int = 300,
        tight: bool = True,
        use: str | None = None,
        **kwargs: Any,
    ) -> list[Any]:
        """Plot current run results using the configured plotting backend."""
        from bucktrader.plot import Plot

        if plotter is None:
            plotter = Plot()

        strategies = kwargs.pop("strategies", None)
        if strategies is None:
            strategies = self._results
        if not isinstance(strategies, list):
            strategies = [strategies]

        figs = plotter.plot(
            strategies=strategies,
            numfigs=numfigs,
            start=start,
            end=end,
            width=width,
            height=height,
            dpi=dpi,
            tight=tight,
            use=use,
            **kwargs,
        )

        if iplot:
            try:
                import matplotlib.pyplot as plt

                plt.show()
            except Exception:
                pass

        return figs

    @property
    def datas(self) -> list[Any]:
        """Return the list of registered data feeds."""
        return self._datas

    def __repr__(self) -> str:
        return (
            f"Cortex(datas={len(self._datas)}, strats={len(self._strats)}, "
            f"preload={self.p_preload}, runonce={self.p_runonce})"
        )
