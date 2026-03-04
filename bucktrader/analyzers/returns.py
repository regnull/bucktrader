"""Returns, AnnualReturn, and TimeReturn analyzers.

Returns     -- Total, average, and compound returns.
AnnualReturn -- Year-by-year returns.
TimeReturn   -- Period-by-period returns.
"""

from __future__ import annotations

import math
from typing import Any

from bucktrader.analyzer import Analyzer, AutoOrderedDict, TimeFrameAnalyzerBase
from bucktrader.dataseries import TimeFrame


class Returns(Analyzer):
    """Track total, average, and compound returns.

    Records the initial portfolio value at start() and computes
    cumulative metrics at stop().
    """

    def __init__(self, strategy: Any = None) -> None:
        super().__init__(strategy)
        self._initial_value: float | None = None
        self._returns: list[float] = []
        self._last_value: float | None = None

    def start(self) -> None:
        if self.broker is not None:
            self._initial_value = self.broker.getvalue()
            self._last_value = self._initial_value

    def next(self) -> None:
        if self.broker is None:
            return
        current = self.broker.getvalue()
        if self._last_value is not None and self._last_value != 0:
            ret = (current / self._last_value) - 1.0
            self._returns.append(ret)
        self._last_value = current

    def stop(self) -> None:
        r = self.rets

        if (
            self._initial_value is not None
            and self._initial_value != 0
            and self._last_value is not None
        ):
            r.rtot = (self._last_value / self._initial_value) - 1.0
        else:
            r.rtot = 0.0

        if self._returns:
            r.ravg = sum(self._returns) / len(self._returns)
        else:
            r.ravg = 0.0

        # Compound return: product of (1+r_i) - 1
        compound = 1.0
        for ret in self._returns:
            compound *= (1.0 + ret)
        r.rnorm = compound - 1.0


class AnnualReturn(Analyzer):
    """Year-by-year returns.

    Tracks portfolio value at year boundaries and computes yearly returns.
    Results stored in ``rets`` keyed by year (int).
    """

    def __init__(self, strategy: Any = None) -> None:
        super().__init__(strategy)
        self._year_start_value: float | None = None
        self._current_year: int | None = None
        self._last_value: float | None = None

    def start(self) -> None:
        if self.broker is not None:
            self._year_start_value = self.broker.getvalue()
            self._last_value = self._year_start_value

    def next(self) -> None:
        if self.broker is None or self.data is None:
            return

        current_value = self.broker.getvalue()
        self._last_value = current_value

        # Try to get the current date.
        dt = self._get_dt()
        if dt is None:
            return

        year = dt.year
        if self._current_year is None:
            self._current_year = year
            self._year_start_value = current_value
        elif year != self._current_year:
            # Year boundary crossed. Record the previous year's return.
            if self._year_start_value and self._year_start_value != 0:
                ret = (current_value / self._year_start_value) - 1.0
                self.rets[self._current_year] = ret
            self._current_year = year
            self._year_start_value = current_value

    def stop(self) -> None:
        # Record the final year.
        if (
            self._current_year is not None
            and self._year_start_value is not None
            and self._year_start_value != 0
            and self._last_value is not None
        ):
            ret = (self._last_value / self._year_start_value) - 1.0
            self.rets[self._current_year] = ret

    def _get_dt(self) -> Any:
        """Extract the current datetime from the data feed."""
        if self.data is None:
            return None
        dt_line = getattr(self.data, "datetime", None)
        if dt_line is None:
            return None
        if hasattr(dt_line, "__getitem__"):
            try:
                from bucktrader.dataseries import num2date
                val = float(dt_line[0])
                if not math.isnan(val):
                    return num2date(val)
            except (IndexError, TypeError, ValueError):
                pass
        return None


class TimeReturn(TimeFrameAnalyzerBase):
    """Period-by-period returns.

    Computes the return for each time period (day, week, month, year)
    and stores them in ``rets`` keyed by the period datetime.
    """

    params = (
        ("timeframe", TimeFrame.Days),
        ("compression", 1),
        ("fund", None),
    )

    def __init__(self, strategy: Any = None, **kwargs: Any) -> None:
        super().__init__(strategy, **kwargs)
        self._period_start_value: float | None = None

    def start(self) -> None:
        if self.broker is not None:
            self._period_start_value = self.broker.getvalue()

    def on_dt_over(self, dtkey: Any) -> None:
        """Record the return for the period that just ended."""
        if self.broker is None:
            return

        current_value = self.broker.getvalue()
        if (
            self._period_start_value is not None
            and self._period_start_value != 0
        ):
            ret = (current_value / self._period_start_value) - 1.0
            self.rets[dtkey] = ret

        self._period_start_value = current_value
