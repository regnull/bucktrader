"""Integration and end-to-end tests (TER-400)."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pytest

from bucktrader.analyzers import Returns, TradeAnalyzer
from bucktrader.cortex import Cortex, OptReturn
from bucktrader.dataseries import TimeFrame
from bucktrader.feed import GenericCSVData
from bucktrader.indicators import EMA, SMA
from bucktrader.observers import DrawDown as DrawDownObserver
from bucktrader.signal import SignalType
from bucktrader.strategy import Strategy


CSV_HEADER = "Date,Open,High,Low,Close,Volume,OpenInterest"
CSV_ROWS = [
    "2024-01-02,100.00,102.50,99.50,101.00,10000,500",
    "2024-01-03,101.00,103.00,100.00,102.50,12000,510",
    "2024-01-04,102.50,104.00,101.50,103.00,11000,520",
    "2024-01-05,103.00,105.00,102.00,104.50,13000,530",
    "2024-01-08,104.50,106.50,103.50,105.00,14000,540",
    "2024-01-09,105.00,107.00,104.00,106.00,15000,550",
    "2024-01-10,106.00,108.00,105.00,107.50,13500,560",
    "2024-01-11,107.50,109.00,106.50,108.00,14500,570",
]


def _write_csv(path: Path, rows: list[str]) -> Path:
    path.write_text(CSV_HEADER + "\n" + "\n".join(rows) + "\n")
    return path


def _data(path: Path) -> GenericCSVData:
    return GenericCSVData(
        dataname=path,
        dtformat="%Y-%m-%d",
        open_col=1,
        high_col=2,
        low_col=3,
        close_col=4,
        volume_col=5,
        openinterest_col=6,
    )


class RoundTripStrategy(Strategy):
    def __init__(self) -> None:
        super().__init__()
        self._bars = 0

    def _next(self) -> None:
        self._bars += 1
        if self._bars == 1:
            self.buy(size=5)
        elif self._bars == 4:
            self.sell(size=5)


class CountBarsStrategy(Strategy):
    def __init__(self) -> None:
        super().__init__()
        self.bars = 0

    def _next(self) -> None:
        self.bars += 1


class IndicatorChainStrategy(Strategy):
    def __init__(self) -> None:
        super().__init__()
        self.sma = None
        self.ema = None
        self.last_val = math.nan

    def start(self) -> None:
        self.sma = SMA(self.data, period=3)
        self.ema = EMA(self.sma, period=2)

    def _next(self) -> None:
        # Child indicators are part of integration for this strategy.
        self.sma.lines.forward()
        self.sma.next()
        self.ema.lines.forward()
        self.ema.next()
        self.last_val = self.ema.lines.av[0]


class SignalLongIndicator:
    def __getitem__(self, idx: int) -> float:
        return 1.0


class SignalStrategyDemo(Strategy):
    def start(self) -> None:
        self.signal_add(SignalType.LONG, SignalLongIndicator())

    def _next(self) -> None:
        self._process_signals()


class BracketStrategy(Strategy):
    def __init__(self) -> None:
        super().__init__()
        self._fired = False

    def _next(self) -> None:
        if not self._fired:
            self.buy_bracket(size=1, price=100.0, stopprice=95.0, limitprice=110.0)
            self._fired = True


class ParamMockStrategy:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._params = kwargs
        self.datas = []
        self.data = None
        self.broker = None
        self.env = None
        self.cortex = None
        self._lineiterators = {0: [], 1: [], 2: []}
        self._analyzers = []
        self._bars = 0

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def _next(self) -> None:
        self._bars += 1

    def notify_order(self, order: Any) -> None:
        pass

    def notify_trade(self, trade: Any) -> None:
        pass

    def notify_cashvalue(self, cash: float, value: float) -> None:
        pass

    def notify_fund(self, cash: float, value: float, fv: float, shares: float) -> None:
        pass


class TestIntegrationSuite:
    def test_full_backtest_flow(self, tmp_path: Path):
        csv = _write_csv(tmp_path / "full.csv", CSV_ROWS)
        c = Cortex(preload=False, runonce=False, stdstats=False)
        c.adddata(_data(csv))
        c.addstrategy(RoundTripStrategy)
        res = c.run()
        strat = res[0]
        assert strat._bars == len(CSV_ROWS)
        # Buy + sell submitted by strategy.
        assert len(strat._orders) >= 2

    def test_multi_data_sync(self, tmp_path: Path):
        csv1 = _write_csv(tmp_path / "d1.csv", CSV_ROWS)
        csv2 = _write_csv(tmp_path / "d2.csv", CSV_ROWS[:5])
        c = Cortex(preload=False, runonce=False, stdstats=False)
        c.adddata(_data(csv1), name="A")
        c.adddata(_data(csv2), name="B")
        c.addstrategy(CountBarsStrategy)
        res = c.run()
        assert res[0].bars >= 5

    def test_optimization_end_to_end(self, tmp_path: Path):
        csv = _write_csv(tmp_path / "opt.csv", CSV_ROWS)
        c = Cortex(preload=False, runonce=False, optreturn=True, stdstats=False)
        c.adddata(_data(csv))
        c.optstrategy(ParamMockStrategy, period=[3, 5], threshold=[0.1, 0.2])
        res = c.run()
        assert len(res) == 4
        assert all(isinstance(x, OptReturn) for x in res)

    def test_resample_and_replay_paths(self, tmp_path: Path):
        csv1 = _write_csv(tmp_path / "resample.csv", CSV_ROWS)
        csv2 = _write_csv(tmp_path / "replay.csv", CSV_ROWS)

        c1 = Cortex(preload=False, runonce=False, stdstats=False)
        d1 = _data(csv1)
        c1.resampledata(d1, timeframe=TimeFrame.Weeks, compression=1)
        c1.addstrategy(CountBarsStrategy)
        r1 = c1.run()[0].bars
        assert r1 > 0

        c2 = Cortex(preload=False, runonce=False, stdstats=False)
        d2 = _data(csv2)
        c2.replaydata(d2, timeframe=TimeFrame.Weeks, compression=1)
        c2.addstrategy(CountBarsStrategy)
        r2 = c2.run()[0].bars
        assert r2 > 0

    def test_indicator_chain_integration(self, tmp_path: Path):
        csv = _write_csv(tmp_path / "ind.csv", CSV_ROWS)
        c = Cortex(preload=False, runonce=False, stdstats=False)
        c.adddata(_data(csv))
        c.addstrategy(IndicatorChainStrategy)
        strat = c.run()[0]
        assert not math.isnan(strat.last_val)

    def test_analyzer_and_observer_outputs(self, tmp_path: Path):
        csv = _write_csv(tmp_path / "ao.csv", CSV_ROWS)
        c = Cortex(preload=False, runonce=False, stdstats=False)
        c.adddata(_data(csv))
        c.addstrategy(RoundTripStrategy)
        c.addanalyzer(Returns)
        c.addanalyzer(TradeAnalyzer)
        c.addobserver(DrawDownObserver)
        strat = c.run()[0]

        # analyzers should have final outputs
        assert len(strat._analyzers) == 2
        returns = strat._analyzers[0].get_analysis()
        assert "rtot" in returns
        # observer lines should have been advanced through bars
        observers = strat._lineiterators[2]
        assert observers
        dd_obs = next(o for o in observers if type(o).__name__ == "DrawDown")
        assert len(dd_obs.lines.drawdown) > 0

    def test_memory_mode_exactbars(self, tmp_path: Path):
        csv = _write_csv(tmp_path / "mem.csv", CSV_ROWS)
        c = Cortex(exactbars=True, preload=True, runonce=True, stdstats=False)
        c.adddata(_data(csv))
        c.addstrategy(CountBarsStrategy)
        res = c.run()
        assert c.p_preload is False
        assert c.p_runonce is False
        assert res[0].bars == len(CSV_ROWS)

    def test_signal_strategy_integration(self, tmp_path: Path):
        csv = _write_csv(tmp_path / "sig.csv", CSV_ROWS)
        c = Cortex(preload=False, runonce=False, stdstats=False)
        c.adddata(_data(csv))
        c.addstrategy(SignalStrategyDemo)
        strat = c.run()[0]
        assert len(strat._orders) > 0

    def test_bracket_order_and_costs_integration(self, tmp_path: Path):
        csv1 = _write_csv(tmp_path / "bracket.csv", CSV_ROWS)
        csv2 = _write_csv(tmp_path / "base.csv", CSV_ROWS)
        csv3 = _write_csv(tmp_path / "costs.csv", CSV_ROWS)

        # Bracket path
        bracket = Cortex(preload=False, runonce=False, stdstats=False)
        bracket.adddata(_data(csv1))
        bracket.addstrategy(BracketStrategy)
        s_bracket = bracket.run()[0]
        assert len(s_bracket._orders) >= 3

        # Commission/slippage path (market roundtrip)
        base = Cortex(preload=False, runonce=False, stdstats=False)
        base.adddata(_data(csv2))
        base.addstrategy(RoundTripStrategy)
        base_strat = base.run()[0]

        cost = Cortex(preload=False, runonce=False, stdstats=False)
        cost.adddata(_data(csv3))
        cost.addstrategy(RoundTripStrategy)
        cost.broker.slip_perc = 0.01
        cost.broker.slip_open = True
        cost.broker.setcommission(commission=0.002)
        cost_strat = cost.run()[0]

        base_order = next(o for o in base_strat._orders if o.status == o.Status.Completed)
        cost_order = next(o for o in cost_strat._orders if o.status == o.Status.Completed)
        assert cost_order.executed.comm > 0.0
        assert cost_order.executed.price != base_order.executed.price
