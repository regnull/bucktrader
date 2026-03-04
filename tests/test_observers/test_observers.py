"""Tests for built-in observers."""

from __future__ import annotations

import math
from datetime import datetime
from types import SimpleNamespace

import pytest

from bucktrader.dataseries import date2num
from bucktrader.observers.benchmark import Benchmark
from bucktrader.observers.broker_obs import Broker
from bucktrader.observers.buysell import BuySell
from bucktrader.observers.drawdown_obs import DrawDown
from bucktrader.observers.fundvalue import FundValue
from bucktrader.observers.timereturn_obs import TimeReturn
from bucktrader.observers.trades_obs import Trades
from bucktrader.order import OrderStatus


class _FakeBroker:
    def __init__(self, cash_values: list[float], portfolio_values: list[float]) -> None:
        self._cash_values = cash_values
        self._portfolio_values = portfolio_values
        self._idx = 0

    def set_bar(self, idx: int) -> None:
        self._idx = idx

    def getcash(self) -> float:
        return self._cash_values[self._idx]

    def getvalue(self) -> float:
        return self._portfolio_values[self._idx]

    def get_fundvalue(self) -> float:
        return self._portfolio_values[self._idx] / 10.0


def _strategy_with_broker(
    cash_values: list[float], portfolio_values: list[float]
) -> SimpleNamespace:
    return SimpleNamespace(
        broker=_FakeBroker(cash_values, portfolio_values),
        data=None,
        datas=[],
    )


class TestBrokerObserver:
    def test_records_cash_and_value(self):
        strat = _strategy_with_broker([1000.0], [1250.0])
        obs = Broker(strategy=strat)

        obs.forward()
        obs.next()

        assert obs.lines.cash[0] == pytest.approx(1000.0)
        assert obs.lines.value[0] == pytest.approx(1250.0)


class TestBuySellObserver:
    def test_marks_completed_buy_and_sell_prices(self):
        obs = BuySell(strategy=None)

        buy_order = SimpleNamespace(
            status=OrderStatus.Completed,
            is_buy=True,
            executed=SimpleNamespace(price=101.5),
        )
        sell_order = SimpleNamespace(
            status=OrderStatus.Completed,
            is_buy=False,
            executed=SimpleNamespace(price=104.0),
        )
        obs.notify_order(buy_order)
        obs.notify_order(sell_order)

        obs.forward()
        obs.next()

        assert obs.lines.buy[0] == pytest.approx(101.5)
        assert obs.lines.sell[0] == pytest.approx(104.0)


class TestTradesObserver:
    def test_splits_closed_trade_pnl_into_plus_and_minus(self):
        obs = Trades(strategy=None)
        obs.notify_trade(SimpleNamespace(isclosed=True, pnlcomm=10.0))
        obs.notify_trade(SimpleNamespace(isclosed=True, pnlcomm=-4.0))

        obs.forward()
        obs.next()

        assert obs.lines.pnlplus[0] == pytest.approx(10.0)
        assert obs.lines.pnlminus[0] == pytest.approx(-4.0)

        # Next bar with no trades should reset both lines to NaN.
        obs.forward()
        obs.next()
        assert math.isnan(obs.lines.pnlplus[0])
        assert math.isnan(obs.lines.pnlminus[0])


class TestDrawDownObserver:
    def test_tracks_current_and_max_drawdown_lines(self):
        strat = _strategy_with_broker([0.0, 0.0, 0.0], [100.0, 80.0, 90.0])
        obs = DrawDown(strategy=strat)
        obs.start()

        obs.forward()
        strat.broker.set_bar(1)
        obs.next()
        assert obs.lines.drawdown[0] == pytest.approx(20.0)
        assert obs.lines.maxdrawdown[0] == pytest.approx(20.0)

        obs.forward()
        strat.broker.set_bar(2)
        obs.next()
        assert obs.lines.drawdown[0] == pytest.approx(10.0)
        assert obs.lines.maxdrawdown[0] == pytest.approx(20.0)


class _SequenceLine:
    def __init__(self, values: list[float]) -> None:
        self._values = values
        self._idx = 0

    def set_bar(self, idx: int) -> None:
        self._idx = idx

    def __getitem__(self, ago: int) -> float:
        return self._values[self._idx + ago]


class _FakeData:
    def __init__(self, closes: list[float], dts: list[Any]) -> None:
        self.close = _SequenceLine(closes)
        self.datetime = _SequenceLine([date2num(dt) for dt in dts])

    def set_bar(self, idx: int) -> None:
        self.close.set_bar(idx)
        self.datetime.set_bar(idx)


class TestAdditionalObservers:
    def test_fund_value_observer(self):
        strat = _strategy_with_broker([1000.0], [2500.0])
        obs = FundValue(strategy=strat)
        obs.forward()
        obs.next()
        assert obs.lines.fundvalue[0] == pytest.approx(250.0)

    def test_timereturn_observer(self):
        dts = [datetime(2024, 1, 2), datetime(2024, 1, 3)]
        data = _FakeData([100.0, 100.0], dts)
        strat = _strategy_with_broker([0.0, 0.0], [100.0, 110.0])
        strat.data = data
        obs = TimeReturn(strategy=strat)
        obs.start()

        data.set_bar(0)
        obs.forward()
        obs.next()
        assert math.isnan(obs.lines.timereturn[0])

        strat.broker.set_bar(1)
        data.set_bar(1)
        obs.forward()
        obs.next()
        assert obs.lines.timereturn[0] == pytest.approx(0.10)

    def test_benchmark_observer(self):
        dts = [datetime(2024, 1, 2), datetime(2024, 1, 3)]
        data = _FakeData([100.0, 105.0], dts)
        strat = SimpleNamespace(data=data, datas=[data], broker=None)
        obs = Benchmark(strategy=strat, data=data)

        data.set_bar(0)
        obs.forward()
        obs.next()
        assert math.isnan(obs.lines.bench[0])

        data.set_bar(1)
        obs.forward()
        obs.next()
        assert obs.lines.bench[0] == pytest.approx(0.05)
