"""Comprehensive tests for the Cortex engine (bucktrader.cortex)."""

from __future__ import annotations

import io
import math
import tempfile
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from bucktrader.broker import BackBroker, BrokerBase
from bucktrader.cortex import Cortex, OptReturn, _StratEntry
from bucktrader.dataseries import TimeFrame, date2num, num2date
from bucktrader.feed import GenericCSVData
from bucktrader.timer import SESSION_START, Timer


# -- Sample Data ---------------------------------------------------------------

SAMPLE_CSV_HEADER = "Date,Open,High,Low,Close,Volume,OpenInterest"

SAMPLE_CSV_ROWS = [
    "2024-01-02,100.00,102.50,99.50,101.00,10000,500",
    "2024-01-03,101.00,103.00,100.00,102.50,12000,510",
    "2024-01-04,102.50,104.00,101.50,103.00,11000,520",
    "2024-01-05,103.00,105.00,102.00,104.50,13000,530",
    "2024-01-08,104.50,106.50,103.50,105.00,14000,540",
    "2024-01-09,105.00,107.00,104.00,106.00,15000,550",
    "2024-01-10,106.00,108.00,105.00,107.50,13500,560",
    "2024-01-11,107.50,109.00,106.50,108.00,14500,570",
    "2024-01-12,108.00,110.00,107.00,109.50,16000,580",
    "2024-01-15,109.50,111.00,108.50,110.00,15500,590",
]

NUM_ROWS = len(SAMPLE_CSV_ROWS)

SAMPLE_CSV = SAMPLE_CSV_HEADER + "\n" + "\n".join(SAMPLE_CSV_ROWS) + "\n"


# -- Mock Strategy -------------------------------------------------------------


class MockStrategy:
    """Minimal strategy stub for testing the Cortex engine.

    Tracks calls to lifecycle methods and notifications.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.datas: list[Any] = []
        self.data: Any = None
        self.broker: Any = None
        self.env: Any = None
        self.cortex: Any = None
        self._orders: list[Any] = []
        self._trades: dict[Any, Any] = {}
        self._lineiterators: dict[int, list[Any]] = {0: [], 1: [], 2: []}
        self._minperiod: int = 1
        self._bar_count: int = 0
        self._analyzers: list[Any] = []
        self._params = dict(kwargs)

        # Tracking for test assertions.
        self.started: bool = False
        self.stopped: bool = False
        self.order_notifications: list[Any] = []
        self.trade_notifications: list[Any] = []
        self.cashvalue_notifications: list[tuple[float, float]] = []
        self.fund_notifications: list[tuple[float, float, float, float]] = []
        self.timer_notifications: list[Any] = []
        self.next_open_calls: int = 0
        self.once_called: bool = False
        self.oncepost_calls: int = 0

    def start(self) -> None:
        self.started = True

    def prenext(self) -> None:
        pass

    def nextstart(self) -> None:
        self.next()

    def next(self) -> None:
        self._bar_count += 1

    def stop(self) -> None:
        self.stopped = True

    def next_open(self) -> None:
        self.next_open_calls += 1

    def notify_order(self, order: Any) -> None:
        self.order_notifications.append(order)

    def notify_trade(self, trade: Any) -> None:
        self.trade_notifications.append(trade)

    def notify_cashvalue(self, cash: float, value: float) -> None:
        self.cashvalue_notifications.append((cash, value))

    def notify_fund(
        self, cash: float, value: float, fv: float, shares: float
    ) -> None:
        self.fund_notifications.append((cash, value, fv, shares))

    def notify_timer(self, timer: Any, when: Any, *args: Any, **kwargs: Any) -> None:
        self.timer_notifications.append((timer, when, args, kwargs))

    def _once(self) -> None:
        self.once_called = True

    def _oncepost(self, dt: float) -> None:
        self.oncepost_calls += 1
        self.next()

    def _next(self) -> None:
        self.next()


# -- Fixtures ------------------------------------------------------------------


@pytest.fixture
def csv_file(tmp_path: Path) -> Path:
    """Write sample CSV to a temporary file."""
    p = tmp_path / "sample.csv"
    p.write_text(SAMPLE_CSV)
    return p


@pytest.fixture
def csv_data(csv_file: Path) -> GenericCSVData:
    """Create a GenericCSVData feed from the sample CSV."""
    return GenericCSVData(
        dataname=csv_file,
        dtformat="%Y-%m-%d",
        open_col=1,
        high_col=2,
        low_col=3,
        close_col=4,
        volume_col=5,
        openinterest_col=6,
    )


@pytest.fixture
def cortex() -> Cortex:
    """Create a default Cortex instance."""
    return Cortex()


# -- Cortex Creation and Defaults ---------------------------------------------


class TestCortexDefaults:
    """Cortex is created with correct defaults."""

    def test_default_parameters(self):
        c = Cortex()
        assert c.p_preload is True
        assert c.p_runonce is True
        assert c.p_live is False
        assert c.p_maxcpus is None
        assert c.p_stdstats is True
        assert c.p_exactbars is False
        assert c.p_optdatas is True
        assert c.p_optreturn is True
        assert c.p_objcache is False
        assert c.p_writer is False
        assert c.p_tradehistory is False
        assert c.p_oldsync is False
        assert c.p_tz is None
        assert c.p_cheat_on_open is False
        assert c.p_broker_coo is True
        assert c.p_quicknotify is False

    def test_custom_parameters(self):
        c = Cortex(
            preload=False,
            runonce=False,
            live=True,
            maxcpus=4,
            stdstats=False,
        )
        assert c.p_preload is False
        assert c.p_runonce is False
        assert c.p_live is True
        assert c.p_maxcpus == 4
        assert c.p_stdstats is False

    def test_default_broker(self):
        c = Cortex()
        assert isinstance(c.broker, BackBroker)
        assert c.broker.startingcash == 10000.0

    def test_empty_registries(self):
        c = Cortex()
        assert len(c._datas) == 0
        assert len(c._strats) == 0
        assert len(c._indicators) == 0
        assert len(c._observers) == 0
        assert len(c._analyzers) == 0
        assert len(c._writers) == 0
        assert len(c._timers) == 0

    def test_repr(self):
        c = Cortex()
        text = repr(c)
        assert "Cortex" in text
        assert "datas=0" in text


# -- Data Feed Registration ---------------------------------------------------


class TestDataFeedRegistration:
    """Data feeds can be registered and configured."""

    def test_adddata(self, cortex, csv_data):
        cortex.adddata(csv_data)
        assert len(cortex.datas) == 1
        assert cortex.datas[0] is csv_data

    def test_adddata_with_name(self, cortex, csv_data):
        cortex.adddata(csv_data, name="SPY")
        assert csv_data.p_name == "SPY"

    def test_adddata_multiple(self, cortex, tmp_path):
        d1 = GenericCSVData(
            dataname=tmp_path / "a.csv",
            dtformat="%Y-%m-%d",
        )
        d2 = GenericCSVData(
            dataname=tmp_path / "b.csv",
            dtformat="%Y-%m-%d",
        )

        # Write minimal csv files for data creation.
        (tmp_path / "a.csv").write_text(SAMPLE_CSV)
        (tmp_path / "b.csv").write_text(SAMPLE_CSV)

        cortex.adddata(d1, name="A")
        cortex.adddata(d2, name="B")

        assert len(cortex.datas) == 2

    def test_adddata_live_autodetect(self, cortex):
        """If data reports as live, Cortex switches to live mode."""

        class LiveData:
            p_name = "live"
            _filters = []

            def islive(self):
                return True

        cortex.adddata(LiveData())
        assert cortex.p_live is True

    def test_resampledata(self, cortex, csv_data):
        cortex.resampledata(csv_data, timeframe=TimeFrame.Days, compression=1)
        assert len(cortex.datas) == 1
        # Check that a filter was added.
        assert len(csv_data._filters) > 0

    def test_replaydata(self, cortex, csv_data):
        cortex.replaydata(csv_data, timeframe=TimeFrame.Days, compression=1)
        assert len(cortex.datas) == 1
        assert len(csv_data._filters) > 0


# -- Strategy Registration ----------------------------------------------------


class TestStrategyRegistration:
    """Strategies can be registered for single runs and optimization."""

    def test_addstrategy(self, cortex):
        idx = cortex.addstrategy(MockStrategy, period=20)
        assert idx == 0
        assert len(cortex._strats) == 1
        assert cortex._strats[0].cls is MockStrategy
        assert cortex._strats[0].kwargs == {"period": 20}
        assert cortex._strats[0].is_opt is False

    def test_addstrategy_multiple(self, cortex):
        cortex.addstrategy(MockStrategy)
        cortex.addstrategy(MockStrategy, fast=10)
        assert len(cortex._strats) == 2

    def test_optstrategy(self, cortex):
        idx = cortex.optstrategy(MockStrategy, period=range(10, 15))
        assert idx == 0
        assert cortex._strats[0].is_opt is True
        assert cortex._strats[0].kwargs == {"period": range(10, 15)}


# -- Broker Setup --------------------------------------------------------------


class TestBrokerSetup:
    """Broker can be configured and replaced."""

    def test_default_broker(self, cortex):
        assert isinstance(cortex.getbroker(), BackBroker)

    def test_setbroker(self, cortex):
        custom = BackBroker(cash=50000.0)
        cortex.setbroker(custom)
        assert cortex.getbroker() is custom
        assert cortex.broker is custom

    def test_broker_property_setter(self, cortex):
        custom = BackBroker(cash=25000.0)
        cortex.broker = custom
        assert cortex.broker is custom
        assert cortex.broker.startingcash == 25000.0


# -- Component Registration ---------------------------------------------------


class TestComponentRegistration:
    """Indicators, observers, analyzers, sizers, writers can be registered."""

    def test_addindicator(self, cortex):
        cortex.addindicator(MagicMock)
        assert len(cortex._indicators) == 1

    def test_addobserver(self, cortex):
        cortex.addobserver(MagicMock)
        assert len(cortex._observers) == 1

    def test_addobservermulti(self, cortex):
        cortex.addobservermulti(MagicMock)
        assert len(cortex._observers) == 1
        # Check per_data flag is set.
        _, _, kw = cortex._observers[0]
        assert kw.get("_per_data") is True

    def test_addanalyzer(self, cortex):
        cortex.addanalyzer(MagicMock)
        assert len(cortex._analyzers) == 1

    def test_addsizer(self, cortex):
        cortex.addsizer(MagicMock)
        assert len(cortex._sizers) == 1

    def test_addsizer_byidx(self, cortex):
        cortex.addsizer_byidx(0, MagicMock)
        assert 0 in cortex._sizers_byidx

    def test_addwriter(self, cortex):
        cortex.addwriter(MagicMock)
        assert len(cortex._writers) == 1

    def test_addcalendar(self, cortex):
        cortex.addcalendar("NYSE")
        assert cortex._calendar == "NYSE"


# -- Timer Registration --------------------------------------------------------


class TestTimerRegistration:
    """Timers can be added and have correct properties."""

    def test_add_timer(self, cortex):
        timer = cortex.add_timer(when=time(10, 0), cheat=True)
        assert isinstance(timer, Timer)
        assert len(cortex._timers) == 1
        assert timer.when == time(10, 0)
        assert timer.cheat is True

    def test_add_multiple_timers(self, cortex):
        cortex.add_timer(when=time(9, 30))
        cortex.add_timer(when=time(16, 0))
        assert len(cortex._timers) == 2


# -- run() with Simple Data and Strategy --------------------------------------


class TestRunBasic:
    """run() processes data through strategy correctly."""

    def test_run_runnext(self, csv_file):
        """Event-driven (_runnext) path processes all bars."""
        cortex = Cortex(preload=False, runonce=False)
        data = GenericCSVData(
            dataname=csv_file,
            dtformat="%Y-%m-%d",
        )
        cortex.adddata(data)
        cortex.addstrategy(MockStrategy)
        results = cortex.run()

        assert len(results) == 1
        strat = results[0]
        assert strat.started is True
        assert strat.stopped is True
        assert strat._bar_count == NUM_ROWS

    def test_run_runonce(self, csv_file):
        """Vectorized (_runonce) path processes all bars."""
        cortex = Cortex(preload=True, runonce=True)
        data = GenericCSVData(
            dataname=csv_file,
            dtformat="%Y-%m-%d",
        )
        cortex.adddata(data)
        cortex.addstrategy(MockStrategy)
        results = cortex.run()

        assert len(results) == 1
        strat = results[0]
        assert strat.started is True
        assert strat.stopped is True
        assert strat.once_called is True
        # _oncepost is called per bar, which calls next().
        assert strat._bar_count == NUM_ROWS

    def test_strategy_receives_datas(self, csv_file):
        """Strategy receives reference to data feeds."""
        cortex = Cortex(preload=False, runonce=False)
        data = GenericCSVData(
            dataname=csv_file,
            dtformat="%Y-%m-%d",
        )
        cortex.adddata(data, name="SPY")
        cortex.addstrategy(MockStrategy)
        results = cortex.run()

        strat = results[0]
        assert len(strat.datas) == 1
        assert strat.data is data

    def test_strategy_receives_broker(self, csv_file):
        """Strategy receives a reference to the broker."""
        cortex = Cortex(preload=False, runonce=False)
        data = GenericCSVData(
            dataname=csv_file,
            dtformat="%Y-%m-%d",
        )
        cortex.adddata(data)
        cortex.addstrategy(MockStrategy)
        results = cortex.run()

        strat = results[0]
        assert strat.broker is cortex.broker

    def test_strategy_receives_env(self, csv_file):
        """Strategy receives a reference to the Cortex."""
        cortex = Cortex(preload=False, runonce=False)
        data = GenericCSVData(
            dataname=csv_file,
            dtformat="%Y-%m-%d",
        )
        cortex.adddata(data)
        cortex.addstrategy(MockStrategy)
        results = cortex.run()

        strat = results[0]
        assert strat.env is cortex
        assert strat.cortex is cortex


# -- _runnext Execution Path ---------------------------------------------------


class TestRunnext:
    """Event-driven execution path."""

    def test_cashvalue_notifications(self, csv_file):
        """Strategy receives cash/value notifications on each bar."""
        cortex = Cortex(preload=False, runonce=False)
        data = GenericCSVData(
            dataname=csv_file,
            dtformat="%Y-%m-%d",
        )
        cortex.adddata(data)
        cortex.addstrategy(MockStrategy)
        results = cortex.run()

        strat = results[0]
        # Should have one notification per bar.
        assert len(strat.cashvalue_notifications) == NUM_ROWS

    def test_fund_notifications(self, csv_file):
        """Strategy receives fund notifications on each bar."""
        cortex = Cortex(preload=False, runonce=False)
        data = GenericCSVData(
            dataname=csv_file,
            dtformat="%Y-%m-%d",
        )
        cortex.adddata(data)
        cortex.addstrategy(MockStrategy)
        results = cortex.run()

        strat = results[0]
        assert len(strat.fund_notifications) == NUM_ROWS

    def test_multiple_strategies(self, csv_file):
        """Multiple strategies each process all bars independently."""
        cortex = Cortex(preload=False, runonce=False)
        data = GenericCSVData(
            dataname=csv_file,
            dtformat="%Y-%m-%d",
        )
        cortex.adddata(data)
        cortex.addstrategy(MockStrategy)
        cortex.addstrategy(MockStrategy)
        results = cortex.run()

        assert len(results) == 2
        for strat in results:
            assert strat._bar_count == NUM_ROWS
            assert strat.started is True
            assert strat.stopped is True


# -- _runonce Execution Path ---------------------------------------------------


class TestRunonce:
    """Vectorized execution path."""

    def test_once_called(self, csv_file):
        """_once() is called on each strategy during vectorized run."""
        cortex = Cortex(preload=True, runonce=True)
        data = GenericCSVData(
            dataname=csv_file,
            dtformat="%Y-%m-%d",
        )
        cortex.adddata(data)
        cortex.addstrategy(MockStrategy)
        results = cortex.run()

        strat = results[0]
        assert strat.once_called is True

    def test_oncepost_called_per_bar(self, csv_file):
        """_oncepost() is called for each bar during vectorized run."""
        cortex = Cortex(preload=True, runonce=True)
        data = GenericCSVData(
            dataname=csv_file,
            dtformat="%Y-%m-%d",
        )
        cortex.adddata(data)
        cortex.addstrategy(MockStrategy)
        results = cortex.run()

        strat = results[0]
        assert strat.oncepost_calls == NUM_ROWS

    def test_cashvalue_during_runonce(self, csv_file):
        """Cash/value notifications fire during vectorized execution."""
        cortex = Cortex(preload=True, runonce=True)
        data = GenericCSVData(
            dataname=csv_file,
            dtformat="%Y-%m-%d",
        )
        cortex.adddata(data)
        cortex.addstrategy(MockStrategy)
        results = cortex.run()

        strat = results[0]
        assert len(strat.cashvalue_notifications) == NUM_ROWS


# -- Broker Notifications -----------------------------------------------------


class TestBrokerNotifications:
    """Broker notifications are delivered to strategies."""

    def test_order_notification(self, csv_file):
        """Pending broker notifications are delivered to strategies."""
        cortex = Cortex(preload=False, runonce=False)
        data = GenericCSVData(
            dataname=csv_file,
            dtformat="%Y-%m-%d",
        )
        cortex.adddata(data)

        class BuyOnceStrategy(MockStrategy):
            """Strategy that buys on bar 3 to trigger notifications."""

            def next(self):
                super().next()
                if self._bar_count == 3 and self.broker and self.data:
                    self.broker.buy(owner=self, data=self.data, size=10)

        cortex.addstrategy(BuyOnceStrategy)
        results = cortex.run()

        strat = results[0]
        # The buy order should have produced at least one notification.
        assert len(strat.order_notifications) > 0


# -- Multi-Data Synchronization ------------------------------------------------


class TestMultiDataSync:
    """Multiple data feeds are synchronized correctly."""

    def test_two_data_feeds(self, tmp_path):
        """Two data feeds with same dates process together."""
        csv1 = tmp_path / "d1.csv"
        csv2 = tmp_path / "d2.csv"

        csv1.write_text(SAMPLE_CSV)
        csv2.write_text(SAMPLE_CSV)

        cortex = Cortex(preload=False, runonce=False)
        d1 = GenericCSVData(dataname=csv1, dtformat="%Y-%m-%d")
        d2 = GenericCSVData(dataname=csv2, dtformat="%Y-%m-%d")

        cortex.adddata(d1, name="D1")
        cortex.adddata(d2, name="D2")
        cortex.addstrategy(MockStrategy)

        results = cortex.run()
        strat = results[0]

        # Strategy should have both data feeds.
        assert len(strat.datas) == 2
        # All bars should be processed.
        assert strat._bar_count == NUM_ROWS

    def test_oldsync_mode(self, tmp_path):
        """oldsync=True uses data0 as the master clock."""
        csv1 = tmp_path / "d1.csv"
        csv1.write_text(SAMPLE_CSV)

        cortex = Cortex(preload=False, runonce=False, oldsync=True)
        d1 = GenericCSVData(dataname=csv1, dtformat="%Y-%m-%d")
        cortex.adddata(d1)
        cortex.addstrategy(MockStrategy)

        results = cortex.run()
        assert results[0]._bar_count == NUM_ROWS


# -- Timer System Integration -------------------------------------------------


class TestTimerIntegration:
    """Timers fire during execution."""

    def test_timer_fires_during_runnext(self, csv_file):
        """Timer fires during event-driven execution."""
        cortex = Cortex(preload=False, runonce=False)
        data = GenericCSVData(
            dataname=csv_file,
            dtformat="%Y-%m-%d",
        )
        cortex.adddata(data)
        cortex.addstrategy(MockStrategy)

        # Add a timer at session start (fires every day).
        cortex.add_timer(when=SESSION_START)

        results = cortex.run()
        strat = results[0]

        # Timer should have fired on each bar.
        assert len(strat.timer_notifications) == NUM_ROWS

    def test_cheat_timer(self, csv_file):
        """Cheat timer fires before broker processing."""
        cortex = Cortex(preload=False, runonce=False, cheat_on_open=True)
        data = GenericCSVData(
            dataname=csv_file,
            dtformat="%Y-%m-%d",
        )
        cortex.adddata(data)
        cortex.addstrategy(MockStrategy)

        cortex.add_timer(when=SESSION_START, cheat=True)

        results = cortex.run()
        strat = results[0]
        assert len(strat.timer_notifications) == NUM_ROWS


# -- Cheat-on-Open Mode -------------------------------------------------------


class TestCheatOnOpen:
    """Cheat-on-open mode calls next_open() before broker."""

    def test_next_open_called(self, csv_file):
        cortex = Cortex(preload=False, runonce=False, cheat_on_open=True)
        data = GenericCSVData(
            dataname=csv_file,
            dtformat="%Y-%m-%d",
        )
        cortex.adddata(data)
        cortex.addstrategy(MockStrategy)
        results = cortex.run()

        strat = results[0]
        assert strat.next_open_calls == NUM_ROWS

    def test_broker_coo_configured(self, csv_file):
        """Broker coo flag is set when cheat_on_open is enabled."""
        cortex = Cortex(
            preload=False, runonce=False,
            cheat_on_open=True, broker_coo=True,
        )
        data = GenericCSVData(
            dataname=csv_file,
            dtformat="%Y-%m-%d",
        )
        cortex.adddata(data)
        cortex.addstrategy(MockStrategy)
        results = cortex.run()

        # The broker's coo should be True.
        assert cortex.broker.coo is True


# -- Optimization (Sequential) ------------------------------------------------


class TestOptimization:
    """Basic sequential optimization."""

    def test_optstrategy_generates_combos(self, csv_file):
        """Optimization generates correct parameter combinations."""
        cortex = Cortex(preload=False, runonce=False)
        data = GenericCSVData(
            dataname=csv_file,
            dtformat="%Y-%m-%d",
        )
        cortex.adddata(data)
        cortex.optstrategy(MockStrategy, period=[10, 20, 30])

        entry = cortex._strats[0]
        combos = cortex._generate_combos(entry)
        assert len(combos) == 3
        assert combos[0] == {"period": 10}
        assert combos[1] == {"period": 20}
        assert combos[2] == {"period": 30}

    def test_optstrategy_cartesian_product(self, csv_file):
        """Multiple list params produce cartesian product."""
        cortex = Cortex(preload=False, runonce=False)
        data = GenericCSVData(
            dataname=csv_file,
            dtformat="%Y-%m-%d",
        )
        cortex.adddata(data)
        cortex.optstrategy(MockStrategy, period=[10, 20], factor=[1.5, 2.0])

        entry = cortex._strats[0]
        combos = cortex._generate_combos(entry)
        assert len(combos) == 4

    def test_optstrategy_runs(self, csv_file):
        """Optimization runs all combinations."""
        cortex = Cortex(preload=False, runonce=False, optreturn=False)
        data = GenericCSVData(
            dataname=csv_file,
            dtformat="%Y-%m-%d",
        )
        cortex.adddata(data)
        cortex.optstrategy(MockStrategy, period=[10, 20])

        results = cortex.run()
        # Two combinations, one strategy each.
        assert len(results) == 2
        for strat in results:
            assert strat._bar_count == NUM_ROWS


# -- OptReturn -----------------------------------------------------------------


class TestOptReturn:
    """OptReturn wraps strategy results correctly."""

    def test_optreturn_creation(self):
        opt = OptReturn(
            params={"period": 20},
            analyzers={"sharpe": {"value": 1.5}},
        )
        assert opt.params == {"period": 20}
        assert opt.analyzers == {"sharpe": {"value": 1.5}}

    def test_optreturn_repr(self):
        opt = OptReturn(params={"period": 20}, analyzers={})
        text = repr(opt)
        assert "OptReturn" in text
        assert "period" in text

    def test_optreturn_during_optimization(self, csv_file):
        """optreturn=True wraps results as OptReturn objects."""
        cortex = Cortex(preload=False, runonce=False, optreturn=True)
        data = GenericCSVData(
            dataname=csv_file,
            dtformat="%Y-%m-%d",
        )
        cortex.adddata(data)
        cortex.optstrategy(MockStrategy, period=[10, 20])

        results = cortex.run()
        assert len(results) == 2
        for r in results:
            assert isinstance(r, OptReturn)


# -- Runtime Parameter Overrides -----------------------------------------------


class TestRuntimeOverrides:
    """run() kwargs override constructor parameters."""

    def test_override_preload(self, csv_file):
        cortex = Cortex(preload=True)
        data = GenericCSVData(
            dataname=csv_file,
            dtformat="%Y-%m-%d",
        )
        cortex.adddata(data)
        cortex.addstrategy(MockStrategy)

        cortex.run(preload=False, runonce=False)
        # After run, the parameter should be overridden.
        assert cortex.p_preload is False

    def test_override_live_disables_preload(self, csv_file):
        """Setting live=True disables preload and runonce."""
        cortex = Cortex(preload=True, runonce=True)
        data = GenericCSVData(
            dataname=csv_file,
            dtformat="%Y-%m-%d",
        )
        cortex.adddata(data)
        cortex.addstrategy(MockStrategy)

        cortex.run(live=True)
        assert cortex.p_preload is False
        assert cortex.p_runonce is False


# -- Edge Cases ----------------------------------------------------------------


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_run_no_data(self):
        """Run with no data feeds is a no-op."""
        cortex = Cortex(preload=False, runonce=False)
        cortex.addstrategy(MockStrategy)
        results = cortex.run()
        assert len(results) == 1
        strat = results[0]
        assert strat._bar_count == 0

    def test_run_no_strategies(self, csv_file):
        """Run with no strategies returns empty list."""
        cortex = Cortex(preload=False, runonce=False)
        data = GenericCSVData(
            dataname=csv_file,
            dtformat="%Y-%m-%d",
        )
        cortex.adddata(data)
        results = cortex.run()
        assert results == []

    def test_exactbars_disables_runonce(self):
        """exactbars mode disables runonce."""
        cortex = Cortex(exactbars=True, runonce=True, preload=True)
        cortex.addstrategy(MockStrategy)
        cortex.run()
        assert cortex.p_runonce is False
        assert cortex.p_preload is False

    def test_runonce_without_preload_fallback(self, csv_file):
        """runonce without preload falls back to runnext."""
        cortex = Cortex(preload=False, runonce=True)
        data = GenericCSVData(
            dataname=csv_file,
            dtformat="%Y-%m-%d",
        )
        cortex.adddata(data)
        cortex.addstrategy(MockStrategy)
        results = cortex.run()

        # runonce should have been disabled since preload is False.
        assert cortex.p_runonce is False
        strat = results[0]
        assert strat._bar_count == NUM_ROWS


# -- datas Property ------------------------------------------------------------


class TestDatasProperty:
    """The datas property returns registered data feeds."""

    def test_datas_empty(self, cortex):
        assert cortex.datas == []

    def test_datas_after_add(self, cortex, csv_data):
        cortex.adddata(csv_data)
        assert len(cortex.datas) == 1
        assert cortex.datas[0] is csv_data


# -- Named Data References on Strategy ----------------------------------------


class TestNamedDataRefs:
    """Strategy receives named data references (data0, data1, dnames)."""

    def test_data0_attribute(self, csv_file):
        cortex = Cortex(preload=False, runonce=False)
        data = GenericCSVData(dataname=csv_file, dtformat="%Y-%m-%d")
        cortex.adddata(data, name="SPY")
        cortex.addstrategy(MockStrategy)
        results = cortex.run()

        strat = results[0]
        assert hasattr(strat, "data0")
        assert strat.data0 is data

    def test_dnames_mapping(self, csv_file):
        cortex = Cortex(preload=False, runonce=False)
        data = GenericCSVData(dataname=csv_file, dtformat="%Y-%m-%d")
        cortex.adddata(data, name="SPY")
        cortex.addstrategy(MockStrategy)
        results = cortex.run()

        strat = results[0]
        assert hasattr(strat, "dnames")
        assert "SPY" in strat.dnames
        assert strat.dnames["SPY"] is data

    def test_multiple_named_data(self, tmp_path):
        csv1 = tmp_path / "d1.csv"
        csv2 = tmp_path / "d2.csv"
        csv1.write_text(SAMPLE_CSV)
        csv2.write_text(SAMPLE_CSV)

        cortex = Cortex(preload=False, runonce=False)
        d1 = GenericCSVData(dataname=csv1, dtformat="%Y-%m-%d")
        d2 = GenericCSVData(dataname=csv2, dtformat="%Y-%m-%d")
        cortex.adddata(d1, name="SPY")
        cortex.adddata(d2, name="QQQ")
        cortex.addstrategy(MockStrategy)
        results = cortex.run()

        strat = results[0]
        assert hasattr(strat, "data0")
        assert hasattr(strat, "data1")
        assert strat.data0 is d1
        assert strat.data1 is d2
        assert strat.dnames["SPY"] is d1
        assert strat.dnames["QQQ"] is d2


# -- Broker Lifecycle ----------------------------------------------------------


class TestBrokerLifecycle:
    """Broker start/stop are called during run."""

    def test_broker_starts_and_stops(self, csv_file):
        cortex = Cortex(preload=False, runonce=False)
        data = GenericCSVData(dataname=csv_file, dtformat="%Y-%m-%d")
        cortex.adddata(data)
        cortex.addstrategy(MockStrategy)

        # The broker's start resets cash; verify it's called.
        cortex.broker.startingcash = 50000.0
        results = cortex.run()

        # After start(), cash should equal startingcash.
        assert cortex.broker.cash == 50000.0

    def test_tradehistory_propagated(self, csv_file):
        """tradehistory parameter is propagated to the broker."""
        cortex = Cortex(preload=False, runonce=False, tradehistory=True)
        data = GenericCSVData(dataname=csv_file, dtformat="%Y-%m-%d")
        cortex.adddata(data)
        cortex.addstrategy(MockStrategy)
        cortex.run()

        assert cortex.broker.tradehistory is True


# -- _StratEntry ---------------------------------------------------------------


class TestStratEntry:
    """Internal _StratEntry has correct fields."""

    def test_fields(self):
        entry = _StratEntry(MockStrategy, (1,), {"a": 2}, is_opt=True)
        assert entry.cls is MockStrategy
        assert entry.args == (1,)
        assert entry.kwargs == {"a": 2}
        assert entry.is_opt is True


# -- Optimization with Range ---------------------------------------------------


class TestOptimizationRange:
    """Optimization with range() produces correct results."""

    def test_range_parameter(self, csv_file):
        cortex = Cortex(preload=False, runonce=False, optreturn=False)
        data = GenericCSVData(dataname=csv_file, dtformat="%Y-%m-%d")
        cortex.adddata(data)
        cortex.optstrategy(MockStrategy, period=range(5, 8))

        results = cortex.run()
        # range(5, 8) = [5, 6, 7] -> 3 combinations.
        assert len(results) == 3
        for strat in results:
            assert strat._bar_count == NUM_ROWS


# -- Runonce Multi-Data --------------------------------------------------------


class TestRunonceMultiData:
    """Vectorized execution with multiple data feeds."""

    def test_two_feeds_runonce(self, tmp_path):
        csv1 = tmp_path / "d1.csv"
        csv2 = tmp_path / "d2.csv"
        csv1.write_text(SAMPLE_CSV)
        csv2.write_text(SAMPLE_CSV)

        cortex = Cortex(preload=True, runonce=True)
        d1 = GenericCSVData(dataname=csv1, dtformat="%Y-%m-%d")
        d2 = GenericCSVData(dataname=csv2, dtformat="%Y-%m-%d")
        cortex.adddata(d1)
        cortex.adddata(d2)
        cortex.addstrategy(MockStrategy)

        results = cortex.run()
        strat = results[0]
        assert strat._bar_count == NUM_ROWS
        assert strat.once_called is True
