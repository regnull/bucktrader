"""Focused tests for Step 9 cortex integrations."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from bucktrader.analyzers.returns import Returns
from bucktrader.cortex import Cortex
from bucktrader.feed import GenericCSVData
from bucktrader.writer import WriterFile

SAMPLE_CSV = """Date,Open,High,Low,Close,Volume,OpenInterest
2024-01-02,100.00,102.50,99.50,101.00,10000,500
2024-01-03,101.00,103.00,100.00,102.50,12000,510
"""


class _MiniStrategy:
    def __init__(self) -> None:
        self.datas: list[Any] = []
        self.data: Any = None
        self.broker: Any = None
        self.env: Any = None
        self.cortex: Any = None
        self._lineiterators: dict[int, list[Any]] = {0: [], 1: [], 2: []}
        self._analyzers: list[Any] = []
        self._bar_count = 0

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def _next(self) -> None:
        self._bar_count += 1

    def _once(self) -> None:
        pass

    def _oncepost(self, dt: float) -> None:
        self._bar_count += 1

    def notify_order(self, order: Any) -> None:
        pass

    def notify_trade(self, trade: Any) -> None:
        pass

    def notify_cashvalue(self, cash: float, value: float) -> None:
        pass

    def notify_fund(
        self, cash: float, value: float, fundvalue: float, shares: float
    ) -> None:
        pass

    def getwriterheaders(self) -> list[str]:
        return ["x", "y"]

    def getwritervalues(self) -> list[Any]:
        return [1, 2]


def _csv_data(path: Path) -> GenericCSVData:
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


class TestCortexStep9:
    def test_stdstats_auto_adds_default_observers(self, tmp_path: Path):
        csv_file = tmp_path / "sample.csv"
        csv_file.write_text(SAMPLE_CSV)

        cortex = Cortex(preload=False, runonce=False, stdstats=True)
        cortex.adddata(_csv_data(csv_file))
        cortex.addstrategy(_MiniStrategy)

        results = cortex.run()
        strat = results[0]

        observer_names = {type(obs).__name__ for obs in strat._lineiterators[2]}
        assert "Broker" in observer_names
        assert "BuySell" in observer_names
        assert "Trades" in observer_names

    def test_writerfile_receives_headers_and_rows(self, tmp_path: Path):
        csv_file = tmp_path / "sample.csv"
        csv_file.write_text(SAMPLE_CSV)

        out = io.StringIO()
        cortex = Cortex(preload=False, runonce=False, stdstats=False)
        cortex.adddata(_csv_data(csv_file))
        cortex.addstrategy(_MiniStrategy)
        cortex.addwriter(WriterFile, out=out, csv_counter=False)

        cortex.run()

        lines = [line.strip() for line in out.getvalue().splitlines() if line.strip()]
        # Header + 2 data bars.
        assert lines[0] == "x,y"
        assert lines[1] == "1,2"
        assert lines[2] == "1,2"

    def test_analyzers_are_bound_to_strategy_instance(self, tmp_path: Path):
        csv_file = tmp_path / "sample.csv"
        csv_file.write_text(SAMPLE_CSV)

        cortex = Cortex(preload=False, runonce=False, stdstats=False)
        cortex.adddata(_csv_data(csv_file))
        cortex.addstrategy(_MiniStrategy)
        cortex.addanalyzer(Returns)

        results = cortex.run()
        strat = results[0]
        assert strat._analyzers
        assert strat._analyzers[0].strategy is strat
