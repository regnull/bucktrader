"""Additional performance analyzers.

Includes:
    Calmar         -- annualized return divided by max drawdown
    VWR            -- variability-weighted return proxy
    PositionsValue -- per-bar position values
    GrossLeverage  -- per-bar gross leverage
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from bucktrader.analyzer import Analyzer
from bucktrader.dataseries import TimeFrame, num2date

_ANNUALIZE_FACTORS = {
    TimeFrame.Days: 252,
    TimeFrame.Weeks: 52,
    TimeFrame.Months: 12,
    TimeFrame.Years: 1,
}


class Calmar(Analyzer):
    """Calmar ratio analyzer.

    Calmar = annualized_return / max_drawdown_fraction
    """

    params = (
        ("timeframe", TimeFrame.Days),
        ("factor", None),
        ("fund", None),
    )

    def __init__(self, strategy: Any = None, **kwargs: Any) -> None:
        super().__init__(strategy)
        self._params: dict[str, Any] = {}
        for name, default in self.__class__.params:
            self._params[name] = kwargs.pop(name, default)

        self._returns: list[float] = []
        self._last_value: float | None = None
        self._peak: float = 0.0
        self._max_drawdown_pct: float = 0.0

    def start(self) -> None:
        if self.broker is not None:
            value = self.broker.getvalue()
            self._last_value = value
            self._peak = value

    def next(self) -> None:
        if self.broker is None:
            return

        value = self.broker.getvalue()
        if self._last_value is not None and self._last_value != 0:
            self._returns.append((value / self._last_value) - 1.0)
        self._last_value = value

        if value > self._peak:
            self._peak = value
        elif self._peak > 0:
            dd = ((self._peak - value) / self._peak) * 100.0
            if dd > self._max_drawdown_pct:
                self._max_drawdown_pct = dd

    def stop(self) -> None:
        n = len(self._returns)
        self.rets.maxdrawdown = self._max_drawdown_pct

        if n == 0:
            self.rets.calmar = None
            return

        compound = 1.0
        for ret in self._returns:
            compound *= 1.0 + ret

        factor = self._params["factor"]
        if factor is None:
            factor = _ANNUALIZE_FACTORS.get(self._params["timeframe"], 252)

        annualized = compound ** (factor / n) - 1.0
        self.rets.rnorm = annualized

        dd_fraction = self._max_drawdown_pct / 100.0
        self.rets.calmar = None if dd_fraction <= 0 else annualized / dd_fraction

    def add_returns(self, returns: list[float], max_drawdown_pct: float) -> None:
        """Helper for tests to inject returns and max drawdown."""
        self._returns.extend(returns)
        self._max_drawdown_pct = max_drawdown_pct


class VWR(Analyzer):
    """Variability-weighted return proxy.

    Uses log-returns to reward smoother equity curves:
        vwr = mean(log(1+r)) / std(log(1+r)) * sqrt(n)
    """

    def __init__(self, strategy: Any = None) -> None:
        super().__init__(strategy)
        self._returns: list[float] = []
        self._last_value: float | None = None

    def start(self) -> None:
        if self.broker is not None:
            self._last_value = self.broker.getvalue()

    def next(self) -> None:
        if self.broker is None:
            return
        value = self.broker.getvalue()
        if self._last_value is not None and self._last_value != 0:
            self._returns.append((value / self._last_value) - 1.0)
        self._last_value = value

    def stop(self) -> None:
        n = len(self._returns)
        if n < 2:
            self.rets.vwr = 0.0
            return

        logs = []
        for ret in self._returns:
            if ret <= -1.0:
                self.rets.vwr = 0.0
                return
            logs.append(math.log1p(ret))

        mean = sum(logs) / n
        variance = sum((x - mean) ** 2 for x in logs) / (n - 1)
        std = math.sqrt(variance)
        self.rets.vwr = 0.0 if std == 0 else (mean / std) * math.sqrt(n)

    def add_returns(self, returns: list[float]) -> None:
        """Helper for tests to inject returns directly."""
        self._returns.extend(returns)


class PositionsValue(Analyzer):
    """Track per-bar position values by data feed."""

    def next(self) -> None:
        if self.broker is None:
            return

        dtkey = _get_dt_key(self.data)
        if dtkey is None:
            dtkey = len(self.rets)

        values: dict[str, float] = {}
        total = 0.0

        for idx, data in enumerate(self.datas):
            pos = self.broker.getposition(data)
            size = getattr(pos, "size", 0.0)
            price = _get_price(data)
            name = getattr(data, "p_name", None) or getattr(data, "name", f"data{idx}")
            values[name] = size * price
            total += values[name]

        self.rets[dtkey] = {"total": total, "positions": values}


class GrossLeverage(Analyzer):
    """Track per-bar gross leverage.

    gross leverage = sum(abs(position market value)) / portfolio value
    """

    def next(self) -> None:
        if self.broker is None:
            return

        portfolio_value = self.broker.getvalue()
        dtkey = _get_dt_key(self.data)
        if dtkey is None:
            dtkey = len(self.rets)

        if portfolio_value == 0:
            self.rets[dtkey] = 0.0
            return

        exposure = 0.0
        for data in self.datas:
            pos = self.broker.getposition(data)
            size = abs(getattr(pos, "size", 0.0))
            if size == 0:
                continue
            price = abs(_get_price(data))
            exposure += size * price

        self.rets[dtkey] = exposure / portfolio_value


def _get_dt_key(data: Any) -> datetime | None:
    if data is None:
        return None
    dt_line = getattr(data, "datetime", None)
    if dt_line is None or not callable(getattr(dt_line, "__getitem__", None)):
        return None
    try:
        val = float(dt_line[0])
    except (TypeError, ValueError, IndexError):
        return None
    if math.isnan(val):
        return None
    return num2date(val)


def _get_price(data: Any) -> float:
    close = getattr(data, "close", None)
    if close is None:
        return 0.0
    if callable(getattr(close, "__getitem__", None)):
        try:
            return float(close[0])
        except (TypeError, ValueError, IndexError):
            return 0.0
    if isinstance(close, (int, float)):
        return float(close)
    return 0.0
