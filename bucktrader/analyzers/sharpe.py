"""SharpeRatio and SharpeRatio_A analyzers.

SharpeRatio = (mean_return - risk_free_rate) / std_return

Optionally annualized by multiplying by sqrt(periods_per_year).
"""

from __future__ import annotations

import math
from typing import Any

from bucktrader.analyzer import Analyzer
from bucktrader.dataseries import TimeFrame


# Annualization factors: number of periods per year.
_ANNUALIZE_FACTORS = {
    TimeFrame.Days: 252,
    TimeFrame.Weeks: 52,
    TimeFrame.Months: 12,
    TimeFrame.Years: 1,
}


class SharpeRatio(Analyzer):
    """Sharpe Ratio analyzer.

    Collects per-bar portfolio returns and computes the Sharpe Ratio at stop().

    Params:
        timeframe    -- annualization reference (default: TimeFrame.Years)
        riskfreerate -- annual risk-free rate (default: 0.01)
        annualize    -- whether to annualize the ratio (default: True)
        factor       -- custom annualization factor (default: None, auto-computed)
        fund         -- use fund-mode values (default: None)
    """

    params = (
        ("timeframe", TimeFrame.Years),
        ("riskfreerate", 0.01),
        ("annualize", True),
        ("factor", None),
        ("fund", None),
    )

    def __init__(self, strategy: Any = None, **kwargs: Any) -> None:
        super().__init__(strategy)

        # Process params.
        self._params: dict[str, Any] = {}
        for name, default in self.__class__.params:
            self._params[name] = kwargs.pop(name, default)

        self._returns: list[float] = []
        self._last_value: float | None = None

    @property
    def p(self) -> Any:
        from bucktrader.analyzer import _ParamAccessor
        return _ParamAccessor(self._params)

    def start(self) -> None:
        """Record the initial portfolio value."""
        if self.strategy is not None and self.broker is not None:
            self._last_value = self.broker.getvalue()

    def next(self) -> None:
        """Compute the return for this bar."""
        if self.broker is None:
            return

        current_value = self.broker.getvalue()
        if self._last_value is not None and self._last_value != 0:
            ret = (current_value / self._last_value) - 1.0
            self._returns.append(ret)

        self._last_value = current_value

    def stop(self) -> None:
        """Compute the Sharpe Ratio from collected returns."""
        if len(self._returns) < 2:
            self.rets.sharperatio = None
            return

        mean_ret = sum(self._returns) / len(self._returns)
        variance = sum((r - mean_ret) ** 2 for r in self._returns) / (
            len(self._returns) - 1
        )
        std_ret = math.sqrt(variance)

        # Convert the annual risk-free rate to a per-period rate.
        annual_rf = self._params["riskfreerate"]
        factor = self._params["factor"]
        timeframe = self._params["timeframe"]

        if factor is None:
            factor = _ANNUALIZE_FACTORS.get(timeframe, 252)

        # Per-period risk-free rate.
        period_rf = annual_rf / factor

        if std_ret == 0:
            self.rets.sharperatio = None
            return

        ratio = (mean_ret - period_rf) / std_ret

        if self._params["annualize"]:
            ratio *= math.sqrt(factor)

        self.rets.sharperatio = ratio

    def add_returns(self, returns: list[float]) -> None:
        """Manually add returns (useful for testing without a broker)."""
        self._returns.extend(returns)


class SharpeRatio_A(SharpeRatio):
    """Pre-annualized Sharpe Ratio (annualize is always True)."""

    params = (
        ("timeframe", TimeFrame.Years),
        ("riskfreerate", 0.01),
        ("annualize", True),
        ("factor", None),
        ("fund", None),
    )
