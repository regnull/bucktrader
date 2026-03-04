"""Tests for plotting system (TER-398)."""

from __future__ import annotations

from types import SimpleNamespace

import matplotlib

matplotlib.use("Agg")

from bucktrader.cortex import Cortex
from bucktrader.dataseries import LineBuffer
from bucktrader.plot import Plot, PlotScheme


def _buf(values):
    b = LineBuffer()
    for v in values:
        b.forward()
        b[0] = v
    return b


def _fake_lines(mapping):
    lines = SimpleNamespace()
    lines._names = tuple(mapping.keys())
    for name, vals in mapping.items():
        setattr(lines, name, _buf(vals))
    return lines


def _fake_component(
    mapping,
    *,
    subplot=True,
    plotlines=None,
):
    return SimpleNamespace(
        lines=_fake_lines(mapping),
        plotinfo={"subplot": subplot, "plot": True},
        plotlines=plotlines or {},
    )


def _fake_strategy():
    data = SimpleNamespace(
        close=_buf([100, 101, 102, 101, 103]),
        open=_buf([99, 100, 101, 100, 102]),
        high=_buf([101, 102, 103, 102, 104]),
        low=_buf([98, 99, 100, 99, 101]),
        volume=_buf([10, 11, 9, 12, 8]),
    )
    overlay_ind = _fake_component({"ovl": [1, 2, 3, 4, 5]}, subplot=False)
    subplot_ind = _fake_component(
        {"sig": [0, 1, 0, -1, 0]},
        subplot=True,
        plotlines={"_fill_gt": (0.0, "green")},
    )
    observer = _fake_component({"obs": [5, 4, 3, 4, 5]}, subplot=True)
    return SimpleNamespace(
        datas=[data],
        _lineiterators={0: [overlay_ind, subplot_ind], 2: [observer]},
    )


class TestPlotModule:
    def test_plot_creates_expected_panels(self):
        strat = _fake_strategy()
        plotter = Plot(PlotScheme(style="line"))
        figs = plotter.plot([strat], numfigs=1, width=8, height=6, dpi=100)
        fig = figs[0]
        # 1 main + 1 subplot indicator + 1 observer
        assert len(fig.axes) >= 3

    def test_candle_style_runs(self):
        strat = _fake_strategy()
        plotter = Plot(PlotScheme(style="candle"))
        figs = plotter.plot([strat], numfigs=1)
        assert len(figs) == 1


class TestCortexPlotIntegration:
    def test_cortex_plot_uses_stored_results(self):
        cortex = Cortex()
        strat = _fake_strategy()
        cortex._results = [strat]
        figs = cortex.plot(iplot=False, numfigs=1)
        assert len(figs) == 1
