"""Tests for built-in analyzers."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from bucktrader.analyzers.drawdown import DrawDown
from bucktrader.analyzers.performance import Calmar, GrossLeverage, PositionsValue, VWR
from bucktrader.analyzers.returns import Returns
from bucktrader.analyzers.sharpe import SharpeRatio
from bucktrader.analyzers.sqn import SQN
from bucktrader.analyzers.trade_analyzer import TradeAnalyzer
from bucktrader.analyzers.transactions import Transactions
from bucktrader.dataseries import date2num
from bucktrader.order import OrderStatus


class _FakeBroker:
    def __init__(self, values: list[float], cash: float = 0.0) -> None:
        self._values = values
        self._idx = 0
        self._cash = cash

    def set_bar(self, idx: int) -> None:
        self._idx = idx

    def getvalue(self) -> float:
        return self._values[self._idx]

    def getcash(self) -> float:
        return self._cash


class _SequenceLine:
    def __init__(self, values: list[float]) -> None:
        self._values = values
        self._idx = 0

    def set_bar(self, idx: int) -> None:
        self._idx = idx

    def __getitem__(self, ago: int) -> float:
        return self._values[self._idx + ago]


class _FakeData:
    def __init__(self, name: str, closes: list[float], dts: list[datetime]) -> None:
        self.p_name = name
        self.close = _SequenceLine(closes)
        self.datetime = _SequenceLine([date2num(dt) for dt in dts])

    def set_bar(self, idx: int) -> None:
        self.close.set_bar(idx)
        self.datetime.set_bar(idx)


class _PositionBroker:
    def __init__(self, positions: dict[Any, float], value: float) -> None:
        self._positions = positions
        self._value = value

    def getposition(self, data: Any) -> Any:
        return SimpleNamespace(size=self._positions.get(data, 0.0))

    def getvalue(self) -> float:
        return self._value


def _strategy_with_broker(values: list[float]) -> SimpleNamespace:
    return SimpleNamespace(
        broker=_FakeBroker(values),
        data=None,
        datas=[],
    )


class TestReturnsAnalyzer:
    def test_total_average_and_compound(self):
        strat = _strategy_with_broker([100.0, 110.0, 99.0])
        analyzer = Returns(strategy=strat)

        analyzer.start()
        strat.broker.set_bar(1)
        analyzer.next()
        strat.broker.set_bar(2)
        analyzer.next()
        analyzer.stop()

        assert analyzer.rets.rtot == pytest.approx(-0.01)
        # Returns are +10% and -10%, average is 0%.
        assert analyzer.rets.ravg == pytest.approx(0.0)
        # Compound return is (1.1 * 0.9) - 1.
        assert analyzer.rets.rnorm == pytest.approx(-0.01)


class TestSharpeRatioAnalyzer:
    def test_ratio_from_manual_returns(self):
        analyzer = SharpeRatio(riskfreerate=0.0, annualize=False)
        analyzer.add_returns([0.10, 0.20, 0.05, 0.15])
        analyzer.stop()

        assert analyzer.rets.sharperatio == pytest.approx(1.93649167)


class TestDrawDownAnalyzer:
    def test_tracks_current_and_maximum_drawdown(self):
        strat = _strategy_with_broker([100.0, 120.0, 90.0, 95.0])
        analyzer = DrawDown(strategy=strat)

        analyzer.start()
        strat.broker.set_bar(1)
        analyzer.next()
        strat.broker.set_bar(2)
        analyzer.next()
        strat.broker.set_bar(3)
        analyzer.next()
        analyzer.stop()

        assert analyzer.rets.drawdown == pytest.approx(20.8333333333)
        assert analyzer.rets.moneydown == pytest.approx(25.0)
        assert analyzer.rets.max.drawdown == pytest.approx(25.0)
        assert analyzer.rets.max.moneydown == pytest.approx(30.0)
        assert analyzer.rets.max.len == 2


class TestSQNAnalyzer:
    def test_sqn_computation(self):
        analyzer = SQN()
        analyzer.notify_trade(SimpleNamespace(isclosed=True, pnlcomm=100.0))
        analyzer.notify_trade(SimpleNamespace(isclosed=True, pnlcomm=50.0))
        analyzer.stop()

        assert analyzer.rets.trades == 2
        assert analyzer.rets.sqn == pytest.approx(3.0)


class TestTransactionsAnalyzer:
    def test_records_latest_execution_bits(self):
        analyzer = Transactions()
        dt = datetime(2024, 1, 2, 10, 0, 0)

        partial_order = SimpleNamespace(
            status=OrderStatus.Partial,
            execution_bits=[
                SimpleNamespace(dt=dt, size=2, price=100.0, value=200.0),
            ],
        )
        analyzer.notify_order(partial_order)

        completed_order = SimpleNamespace(
            status=OrderStatus.Completed,
            execution_bits=[
                SimpleNamespace(dt=dt, size=2, price=100.0, value=200.0),
                SimpleNamespace(dt=dt, size=3, price=101.0, value=303.0),
            ],
        )
        analyzer.notify_order(completed_order)

        assert dt in analyzer.rets
        assert analyzer.rets[dt] == [
            {"size": 2, "price": 100.0, "value": 200.0},
            {"size": 3, "price": 101.0, "value": 303.0},
        ]

    def test_ignores_non_filled_status(self):
        analyzer = Transactions()
        pending_order = SimpleNamespace(
            status=OrderStatus.Accepted,
            execution_bits=[SimpleNamespace(dt=datetime.now(), size=1, price=1, value=1)],
        )
        analyzer.notify_order(pending_order)
        assert analyzer.rets.to_dict() == {}


class TestTradeAnalyzer:
    def test_long_and_short_win_loss_counters(self):
        analyzer = TradeAnalyzer()

        # Long trade opens and wins.
        analyzer.notify_trade(
            SimpleNamespace(
                ref=1,
                justopened=True,
                isclosed=False,
                size=10,
            )
        )
        analyzer.notify_trade(
            SimpleNamespace(
                ref=1,
                justopened=False,
                isclosed=True,
                pnl=100.0,
                pnlcomm=95.0,
                barlen=3,
            )
        )

        # Short trade opens and loses.
        analyzer.notify_trade(
            SimpleNamespace(
                ref=2,
                justopened=True,
                isclosed=False,
                size=-5,
            )
        )
        analyzer.notify_trade(
            SimpleNamespace(
                ref=2,
                justopened=False,
                isclosed=True,
                pnl=-50.0,
                pnlcomm=-55.0,
                barlen=2,
            )
        )

        analyzer.stop()

        assert analyzer.rets.total.total == 2
        assert analyzer.rets.total.closed == 2
        assert analyzer.rets.long.total == 1
        assert analyzer.rets.long.won == 1
        assert analyzer.rets.long.lost == 0
        assert analyzer.rets.short.total == 1
        assert analyzer.rets.short.won == 0
        assert analyzer.rets.short.lost == 1
        assert analyzer.rets.won.total == 1
        assert analyzer.rets.lost.total == 1


class TestPerformanceAnalyzers:
    def test_calmar_ratio(self):
        analyzer = Calmar(factor=3)
        analyzer.add_returns([0.10, 0.10, 0.10], max_drawdown_pct=10.0)
        analyzer.stop()
        assert analyzer.rets.calmar == pytest.approx(3.31, rel=1e-2)

    def test_vwr(self):
        analyzer = VWR()
        analyzer.add_returns([0.10, 0.20, 0.05, 0.15])
        analyzer.stop()
        assert analyzer.rets.vwr > 0

    def test_positions_value(self):
        dts = [datetime(2024, 1, 2)]
        data_a = _FakeData("AAPL", [100.0], dts)
        data_b = _FakeData("MSFT", [50.0], dts)
        data_a.set_bar(0)
        data_b.set_bar(0)

        broker = _PositionBroker({data_a: 2.0, data_b: -3.0}, value=10_000.0)
        strat = SimpleNamespace(
            broker=broker,
            data=data_a,
            datas=[data_a, data_b],
        )
        analyzer = PositionsValue(strategy=strat)
        analyzer.next()

        only_key = next(iter(analyzer.rets.keys()))
        assert analyzer.rets[only_key]["positions"]["AAPL"] == pytest.approx(200.0)
        assert analyzer.rets[only_key]["positions"]["MSFT"] == pytest.approx(-150.0)
        assert analyzer.rets[only_key]["total"] == pytest.approx(50.0)

    def test_gross_leverage(self):
        dts = [datetime(2024, 1, 2)]
        data_a = _FakeData("AAPL", [100.0], dts)
        data_b = _FakeData("MSFT", [50.0], dts)
        data_a.set_bar(0)
        data_b.set_bar(0)

        broker = _PositionBroker({data_a: 2.0, data_b: -3.0}, value=1000.0)
        strat = SimpleNamespace(
            broker=broker,
            data=data_a,
            datas=[data_a, data_b],
        )
        analyzer = GrossLeverage(strategy=strat)
        analyzer.next()

        only_key = next(iter(analyzer.rets.keys()))
        assert analyzer.rets[only_key] == pytest.approx((200.0 + 150.0) / 1000.0)
