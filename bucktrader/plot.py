"""Plotting support for bucktrader."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import matplotlib.pyplot as plt
import numpy as np


@dataclass
class PlotScheme:
    """Global plotting options."""

    style: str = "line"
    volume: bool = True
    voloverlay: bool = True
    volscaling: float = 0.33
    barup: str = "0.75"
    bardown: str = "red"
    grid: bool = True
    rowsmajor: int = 5
    rowsminor: int = 1
    lcolors: tuple[str, ...] = (
        "#1f77b4",
        "#ff7f0e",
        "#2ca02c",
        "#d62728",
        "#9467bd",
        "#8c564b",
        "#e377c2",
        "#7f7f7f",
        "#bcbd22",
        "#17becf",
    )
    fillalpha: float = 0.20


class Plot:
    """Plotter for strategy results."""

    def __init__(self, scheme: PlotScheme | None = None) -> None:
        self.scheme = scheme or PlotScheme()

    def plot(
        self,
        strategies: list[Any],
        numfigs: int = 1,
        start: int | None = None,
        end: int | None = None,
        width: int = 16,
        height: int = 9,
        dpi: int = 300,
        tight: bool = True,
        use: str | None = None,
        **kwargs: Any,
    ) -> list[Any]:
        """Plot one or more strategy results and return matplotlib figures."""
        if use:
            plt.style.use(use)

        if not strategies:
            return []

        figs: list[Any] = []
        for strat in strategies[:numfigs]:
            fig = self._plot_strategy(
                strat,
                start=start,
                end=end,
                width=width,
                height=height,
                dpi=dpi,
                tight=tight,
            )
            figs.append(fig)
        return figs

    def _plot_strategy(
        self,
        strat: Any,
        start: int | None,
        end: int | None,
        width: int,
        height: int,
        dpi: int,
        tight: bool,
    ):
        datas = list(getattr(strat, "datas", []))
        indicators = list(getattr(strat, "_lineiterators", {}).get(0, []))
        observers = list(getattr(strat, "_lineiterators", {}).get(2, []))

        data = datas[0] if datas else None
        if data is None:
            fig, ax = plt.subplots(figsize=(width, height), dpi=dpi)
            ax.set_title(type(strat).__name__)
            return fig

        # Panels: main data + subplot indicators + observers.
        subplot_inds = [i for i in indicators if _is_subplot(i)]
        overlay_inds = [i for i in indicators if not _is_subplot(i)]
        nrows = 1 + len(subplot_inds) + len(observers)
        height_ratios = [self.scheme.rowsmajor] + [self.scheme.rowsminor] * (nrows - 1)

        fig, axes = plt.subplots(
            nrows=nrows,
            ncols=1,
            sharex=True,
            figsize=(width, height),
            dpi=dpi,
            gridspec_kw={"height_ratios": height_ratios},
        )
        if nrows == 1:
            axes = [axes]
        else:
            axes = list(axes)

        x, o, h, l, c, v = _extract_ohlcv(data, start, end)
        ax0 = axes[0]
        self._plot_price(ax0, x, o, h, l, c)

        if self.scheme.volume and self.scheme.voloverlay and v is not None:
            vol_ax = ax0.twinx()
            vol_ax.bar(x, v, alpha=0.25, color="gray", width=0.8)
            vol_ax.set_yticks([])

        color_idx = 0
        for ind in overlay_inds:
            color_idx = self._plot_component(
                ax0, ind, x, start, end, color_idx=color_idx
            )

        row = 1
        for ind in subplot_inds:
            color_idx = self._plot_component(
                axes[row], ind, x, start, end, color_idx=color_idx
            )
            row += 1

        for obs in observers:
            color_idx = self._plot_component(
                axes[row], obs, x, start, end, color_idx=color_idx
            )
            row += 1

        if tight:
            fig.tight_layout()
        return fig

    def _plot_price(self, ax: Any, x: np.ndarray, o, h, l, c) -> None:
        if self.scheme.style == "candle" and o is not None and h is not None and l is not None:
            up = c >= o
            down = ~up
            ax.vlines(x, l, h, color="black", linewidth=0.7)
            ax.bar(
                x[up],
                c[up] - o[up],
                bottom=o[up],
                color=self.scheme.barup,
                width=0.6,
                align="center",
            )
            ax.bar(
                x[down],
                c[down] - o[down],
                bottom=o[down],
                color=self.scheme.bardown,
                width=0.6,
                align="center",
            )
        elif self.scheme.style == "bar":
            ax.bar(x, c, color=self.scheme.lcolors[0], width=0.8)
        else:
            ax.plot(x, c, color=self.scheme.lcolors[0], label="close")
        if self.scheme.grid:
            ax.grid(True, alpha=0.2)

    def _plot_component(
        self,
        ax: Any,
        comp: Any,
        x: np.ndarray,
        start: int | None,
        end: int | None,
        color_idx: int,
    ) -> int:
        plotinfo = getattr(comp, "plotinfo", {}) or {}
        if plotinfo.get("plotskip"):
            return color_idx

        names = tuple(getattr(comp.lines, "_names", ()))
        plotlines = getattr(comp, "plotlines", {}) or {}

        line_cache: dict[str, np.ndarray] = {}
        for name in names:
            cfg = plotlines.get(name, {})
            if cfg.get("_plotskip"):
                continue
            buf = getattr(comp.lines, name)
            y = _slice_array(buf.array, start, end)
            if len(y) == 0:
                continue
            xx = x[: len(y)]
            color = cfg.get("color", self.scheme.lcolors[color_idx % len(self.scheme.lcolors)])
            linewidth = cfg.get("linewidth", 1.2)
            linestyle = cfg.get("linestyle", "-")
            ax.plot(xx, y, color=color, linewidth=linewidth, linestyle=linestyle, label=name)
            line_cache[name] = y
            color_idx += 1

        # Fill directives.
        self._apply_fill_directive(ax, x, line_cache, plotlines.get("_fill_gt"), gt=True)
        self._apply_fill_directive(ax, x, line_cache, plotlines.get("_fill_lt"), gt=False)

        for yhl in plotinfo.get("plotyhlines", []):
            ax.axhline(yhl, color="gray", alpha=0.3, linewidth=0.8)
        for hline in plotinfo.get("plothlines", []):
            ax.axhline(hline, color="gray", alpha=0.3, linewidth=0.8)
        ticks = plotinfo.get("plotyticks", [])
        if ticks:
            ax.set_yticks(ticks)

        if self.scheme.grid:
            ax.grid(True, alpha=0.2)
        return color_idx

    def _apply_fill_directive(
        self,
        ax: Any,
        x: np.ndarray,
        line_cache: dict[str, np.ndarray],
        directive: Any,
        gt: bool,
    ) -> None:
        if not directive:
            return

        color = "green" if gt else "red"
        if isinstance(directive, tuple):
            if len(directive) == 3 and isinstance(directive[0], str) and isinstance(directive[1], str):
                line1 = line_cache.get(directive[0])
                line2 = line_cache.get(directive[1])
                color = directive[2] or color
                if line1 is None or line2 is None:
                    return
                xx = x[: min(len(line1), len(line2))]
                l1 = line1[: len(xx)]
                l2 = line2[: len(xx)]
                where = l1 > l2 if gt else l1 < l2
                ax.fill_between(xx, l1, l2, where=where, color=color, alpha=self.scheme.fillalpha)
                return
            if len(directive) == 2:
                threshold, color = directive
                if not line_cache:
                    return
                first = next(iter(line_cache.values()))
                xx = x[: len(first)]
                where = first > threshold if gt else first < threshold
                ax.fill_between(
                    xx,
                    first,
                    np.full_like(first, threshold),
                    where=where,
                    color=color or ("green" if gt else "red"),
                    alpha=self.scheme.fillalpha,
                )


def _extract_ohlcv(data: Any, start: int | None, end: int | None):
    close = _slice_array(getattr(data, "close").array, start, end)
    x = np.arange(len(close))

    open_line = getattr(data, "open", None)
    high_line = getattr(data, "high", None)
    low_line = getattr(data, "low", None)
    volume_line = getattr(data, "volume", None)

    o = _slice_array(open_line.array, start, end) if open_line is not None else None
    h = _slice_array(high_line.array, start, end) if high_line is not None else None
    l = _slice_array(low_line.array, start, end) if low_line is not None else None
    v = _slice_array(volume_line.array, start, end) if volume_line is not None else None
    return x, o, h, l, close, v


def _slice_array(arr: np.ndarray, start: int | None, end: int | None) -> np.ndarray:
    s = 0 if start is None else max(0, start)
    e = len(arr) if end is None else min(len(arr), end)
    if e <= s:
        return np.array([], dtype=float)
    return np.asarray(arr[s:e], dtype=float)


def _is_subplot(comp: Any) -> bool:
    plotinfo = getattr(comp, "plotinfo", {}) or {}
    return bool(plotinfo.get("subplot", True))
