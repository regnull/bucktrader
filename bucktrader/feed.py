"""Data feed classes: loading, filtering, and delivery of market data.

Implements the data loading protocol described in the spec:
    load() -> _fromstack / _load -> filters -> date filters -> deliver

Key classes:
    AbstractDataBase  - interface / base for all data feeds
    DataBase          - primary concrete base with filter + stack support
    CSVDataBase       - file-based CSV feeds
    GenericCSVData    - flexible column-mapped CSV feed
    DataFrameData     - pandas DataFrame feed
    DataClone         - lightweight view over another feed
    DataFiller        - fills gaps with synthetic bars
    DataFilter        - abstract bar filter base
"""

from __future__ import annotations

import csv
import io
import math
from collections import deque
from datetime import datetime, time, timezone
from enum import IntEnum
from pathlib import Path
from typing import Any, Callable, Optional, Protocol, Sequence, Union

import numpy as np

from bucktrader.dataseries import (
    OHLC_LINES,
    LineBuffer,
    OHLCDateTime,
    TimeFrame,
    date2num,
    num2date,
)

# ── DataStatus ───────────────────────────────────────────────────────────────


class DataStatus(IntEnum):
    """Status notifications emitted by live data feeds."""

    LIVE = 0
    CONNECTED = 1
    DISCONNECTED = 2
    CONNBROKEN = 3
    DELAYED = 4


# ── Filter protocol ─────────────────────────────────────────────────────────


class FilterProtocol(Protocol):
    """Structural type for data filters."""

    def __call__(self, data: "DataBase") -> bool:
        """Process a bar. Return True to consume it, False to keep it."""
        ...

    def last(self, data: "DataBase") -> None:
        """Called when data is exhausted. Flush remaining buffered bars."""
        ...


# ── Bar tuple helper ─────────────────────────────────────────────────────────
# A bar is a simple tuple of floats in the canonical OHLC_LINES order.

BarTuple = tuple[float, ...]


def _current_bar(data: OHLCDateTime) -> BarTuple:
    """Snapshot the current bar values into a tuple."""
    return tuple(data.get_line(i)[0] for i in range(len(OHLC_LINES)))


def _apply_bar(data: OHLCDateTime, bar: BarTuple) -> None:
    """Write a bar tuple onto the current position of *data*."""
    for i, val in enumerate(bar):
        if i < len(OHLC_LINES):
            data.get_line(i)[0] = val


# ── AbstractDataBase ─────────────────────────────────────────────────────────


class AbstractDataBase(OHLCDateTime):
    """Abstract interface for all data feeds.

    Subclasses must implement ``_load`` at minimum.
    """

    def __init__(
        self,
        dataname: Any = None,
        name: str = "",
        compression: int = 1,
        timeframe: TimeFrame = TimeFrame.Days,
        fromdate: Optional[datetime] = None,
        todate: Optional[datetime] = None,
        sessionstart: Optional[time] = None,
        sessionend: Optional[time] = None,
        filters: Optional[list[Any]] = None,
        tz: Optional[Any] = None,
        tzinput: Optional[Any] = None,
        qcheck: float = 0.0,
        calendar: Optional[Any] = None,
    ) -> None:
        super().__init__()
        self.p_dataname = dataname
        self.p_name = name or ""
        self.p_compression = compression
        self.p_timeframe = timeframe
        self.p_fromdate = fromdate
        self.p_todate = todate
        self.p_sessionstart = sessionstart
        self.p_sessionend = sessionend
        self.p_tz = tz
        self.p_tzinput = tzinput
        self.p_qcheck = qcheck
        self.p_calendar = calendar

        # Convert fromdate/todate to float for fast comparison.
        self._fromdate_num: Optional[float] = (
            date2num(fromdate) if fromdate else None
        )
        self._todate_num: Optional[float] = (
            date2num(todate) if todate else None
        )

        # Instantiate filter objects from classes / callables.
        self._filters: list[Any] = []
        for f in filters or []:
            if isinstance(f, type):
                self._filters.append(f(self))
            else:
                self._filters.append(f)

        # Bar stacks used by the filter system.
        self._barstack: deque[BarTuple] = deque()
        self._barstash: deque[BarTuple] = deque()

        self._started = False

    # ── lifecycle ────────────────────────────────────────────────────────

    def start(self) -> None:
        """Called before data loading begins."""
        self._started = True

    def stop(self) -> None:
        """Called after data loading ends."""
        self._started = False

    def islive(self) -> bool:
        """Return True if this is a live (non-historical) feed."""
        return False

    # ── abstract ─────────────────────────────────────────────────────────

    def _load(self) -> bool:
        """Read the next bar from the data source.

        Override in subclasses. Must set line values at [0] and return True
        on success, False when exhausted.
        """
        raise NotImplementedError

    # ── data loading protocol ────────────────────────────────────────────

    def load(self) -> bool:
        """Main entry point: get the next bar.

        Protocol:
            1. forward() all line pointers
            2. Try _fromstack (filters may have buffered bars)
            3. If stack empty, call _load()
            4. Apply filters
            5. Apply date filters
            6. Return True if bar accepted
        """
        self.forward()

        # Try buffered bars first.
        if self._fromstack():
            if not self._check_date_filters():
                # Bar outside requested range -- try loading again.
                return self.load()
            return True

        # Read from source.
        if not self._load():
            # Source exhausted -- check stack one more time.
            if self._fromstack():
                if not self._check_date_filters():
                    return self.load()
                return True
            # Undo the forward -- no valid data.
            self.backwards()
            return False

        # Run filters.
        if self._run_filters():
            # Bar was consumed by a filter -- try loading next.
            return self.load()

        # Date filter.
        if not self._check_date_filters():
            return self.load()

        return True

    def preload(self) -> None:
        """Load all bars into memory, then reset pointer."""
        while self.load():
            pass
        self._last()
        self.home()

    # ── filter helpers ───────────────────────────────────────────────────

    def _run_filters(self) -> bool:
        """Execute filter pipeline. Return True if bar was consumed."""
        for f in self._filters:
            if callable(f):
                # Simple callable filter: f(data) -> bool
                if hasattr(f, "__call__") and not hasattr(f, "last"):
                    if f(self):
                        return True
                else:
                    if f(self):
                        return True
        return False

    def _last(self) -> None:
        """Notify filters that data is exhausted."""
        for f in self._filters:
            if hasattr(f, "last"):
                f.last(self)

    def _check_date_filters(self) -> bool:
        """Return True if the current bar passes fromdate/todate checks."""
        dt_val = self.datetime[0]
        if math.isnan(dt_val):
            return False
        if self._fromdate_num is not None and dt_val < self._fromdate_num:
            return False
        if self._todate_num is not None and dt_val > self._todate_num:
            return False
        return True

    # ── bar stack operations ─────────────────────────────────────────────

    def _save2stack(self, erase: bool = False) -> None:
        """Save current bar to the main stack."""
        bar = _current_bar(self)
        self._barstack.append(bar)
        if erase:
            for i in range(len(OHLC_LINES)):
                self.get_line(i)[0] = math.nan

    def _add2stack(self, bar: BarTuple) -> None:
        """Add a synthetic bar to the main stack."""
        self._barstack.append(bar)

    def _save2stash(self) -> None:
        """Save current bar to the temporary stash."""
        bar = _current_bar(self)
        self._barstash.append(bar)

    def _add2stash(self, bar: BarTuple) -> None:
        """Add a bar to the temporary stash."""
        self._barstash.append(bar)

    def _fromstack(self) -> bool:
        """Pop a bar from the stack and write it to current position.

        Returns True if a bar was available.
        """
        if self._barstack:
            bar = self._barstack.popleft()
            _apply_bar(self, bar)
            return True
        if self._barstash:
            bar = self._barstash.popleft()
            _apply_bar(self, bar)
            return True
        return False

    def _updatebar(self, bar: BarTuple) -> None:
        """Overwrite the current bar with values from *bar*."""
        _apply_bar(self, bar)


# ── DataBase ─────────────────────────────────────────────────────────────────


class DataBase(AbstractDataBase):
    """Primary base class for concrete data feeds.

    Provides the full data loading protocol with filter and stack support.
    Subclasses override ``_load()`` to read from their specific source.
    """

    pass


# ── CSVDataBase ──────────────────────────────────────────────────────────────


class CSVDataBase(DataBase):
    """Base class for CSV-based data feeds.

    Opens the file on ``start()``, reads lines, splits by separator,
    handles headers, and delegates row parsing to ``_loadline()``.
    """

    def __init__(
        self,
        headers: bool = True,
        separator: str = ",",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.p_headers = headers
        self.p_separator = separator

        self._fileobj: Optional[io.TextIOBase] = None
        self._reader: Optional[csv.reader] = None
        self._header_row: Optional[list[str]] = None

    def start(self) -> None:
        super().start()
        dataname = self.p_dataname
        if isinstance(dataname, (str, Path)):
            self._fileobj = open(dataname, "r", newline="")  # noqa: SIM115
        elif hasattr(dataname, "read"):
            self._fileobj = dataname
        else:
            raise ValueError(
                f"CSVDataBase requires a filename or file-like object, got {type(dataname)}"
            )
        self._reader = csv.reader(self._fileobj, delimiter=self.p_separator)
        if self.p_headers:
            try:
                self._header_row = next(self._reader)
            except StopIteration:
                self._header_row = []

    def stop(self) -> None:
        if self._fileobj is not None:
            self._fileobj.close()
            self._fileobj = None
        self._reader = None
        super().stop()

    def _load(self) -> bool:
        if self._reader is None:
            return False
        try:
            tokens = next(self._reader)
        except StopIteration:
            return False
        return self._loadline(tokens)

    def _loadline(self, tokens: list[str]) -> bool:
        """Parse a CSV row into line values. Override in subclasses."""
        raise NotImplementedError


# ── GenericCSVData ───────────────────────────────────────────────────────────


class GenericCSVData(CSVDataBase):
    """Flexible CSV feed with configurable column index mapping.

    Parameters control which CSV column maps to each OHLCV field.
    A column index of ``-1`` means the field is not present.
    """

    def __init__(
        self,
        dtformat: Union[str, Callable[[str], datetime]] = "%Y-%m-%d %H:%M:%S",
        tmformat: str = "%H:%M:%S",
        dt_col: int = 0,
        time_col: int = -1,
        open_col: int = 1,
        high_col: int = 2,
        low_col: int = 3,
        close_col: int = 4,
        volume_col: int = 5,
        openinterest_col: int = 6,
        nullvalue: float = math.nan,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.p_dtformat = dtformat
        self.p_tmformat = tmformat
        self.p_dt_col = dt_col
        self.p_time_col = time_col
        self.p_open_col = open_col
        self.p_high_col = high_col
        self.p_low_col = low_col
        self.p_close_col = close_col
        self.p_volume_col = volume_col
        self.p_openinterest_col = openinterest_col
        self.p_nullvalue = nullvalue

    def _parse_datetime(self, tokens: list[str]) -> float:
        """Parse the datetime (and optional time) columns into a float."""
        dtstr = tokens[self.p_dt_col].strip()
        if callable(self.p_dtformat) and not isinstance(self.p_dtformat, str):
            dt = self.p_dtformat(dtstr)
        else:
            dt = datetime.strptime(dtstr, self.p_dtformat)

        if self.p_time_col >= 0 and self.p_time_col < len(tokens):
            tmstr = tokens[self.p_time_col].strip()
            tm = datetime.strptime(tmstr, self.p_tmformat).time()
            dt = dt.replace(hour=tm.hour, minute=tm.minute, second=tm.second)

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return date2num(dt)

    def _safe_float(self, tokens: list[str], col: int) -> float:
        """Read a float from *tokens[col]*, returning nullvalue on failure."""
        if col < 0 or col >= len(tokens):
            return self.p_nullvalue
        raw = tokens[col].strip()
        if not raw:
            return self.p_nullvalue
        try:
            return float(raw)
        except ValueError:
            return self.p_nullvalue

    def _loadline(self, tokens: list[str]) -> bool:
        try:
            dt_val = self._parse_datetime(tokens)
        except (ValueError, IndexError):
            return False

        self.datetime[0] = dt_val
        self.open[0] = self._safe_float(tokens, self.p_open_col)
        self.high[0] = self._safe_float(tokens, self.p_high_col)
        self.low[0] = self._safe_float(tokens, self.p_low_col)
        self.close[0] = self._safe_float(tokens, self.p_close_col)
        self.volume[0] = self._safe_float(tokens, self.p_volume_col)
        self.openinterest[0] = self._safe_float(
            tokens, self.p_openinterest_col
        )
        return True


# ── DataFrameData ────────────────────────────────────────────────────────────


class DataFrameData(DataBase):
    """Data feed backed by a pandas DataFrame.

    Column mapping accepts:
        None  -- field not present
        str   -- column name
        int   -- column position (0-based)
    If ``datetime_col`` is None the DataFrame index is used.
    """

    def __init__(
        self,
        datetime_col: Optional[Union[str, int]] = "Date",
        open_col: Union[str, int, None] = "Open",
        high_col: Union[str, int, None] = "High",
        low_col: Union[str, int, None] = "Low",
        close_col: Union[str, int, None] = "Close",
        volume_col: Union[str, int, None] = "Volume",
        openinterest_col: Union[str, int, None] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.p_datetime_col = datetime_col
        self.p_open_col = open_col
        self.p_high_col = high_col
        self.p_low_col = low_col
        self.p_close_col = close_col
        self.p_volume_col = volume_col
        self.p_openinterest_col = openinterest_col

        self._df_iter: Any = None
        self._df_len: int = 0
        self._df_idx: int = 0

    def start(self) -> None:
        super().start()
        import pandas as pd

        df = self.p_dataname
        if not isinstance(df, pd.DataFrame):
            raise TypeError(
                f"DataFrameData requires a pandas DataFrame, got {type(df)}"
            )
        self._df = df
        self._df_len = len(df)
        self._df_idx = 0

    def _resolve_col(
        self, col: Union[str, int, None], row: Any, idx: Any
    ) -> float:
        """Extract a float value from a DataFrame row."""
        if col is None:
            return math.nan
        if isinstance(col, str):
            val = row.get(col, math.nan)
        elif isinstance(col, int):
            val = row.iloc[col] if hasattr(row, "iloc") else math.nan
        else:
            val = math.nan
        try:
            return float(val)
        except (ValueError, TypeError):
            return math.nan

    def _resolve_datetime(self, row: Any, idx: Any) -> float:
        """Extract the datetime value and convert to float."""
        import pandas as pd

        if self.p_datetime_col is None:
            # Use the DataFrame index.
            dt = idx
        elif isinstance(self.p_datetime_col, str):
            dt = row.get(self.p_datetime_col, None)
        elif isinstance(self.p_datetime_col, int):
            dt = row.iloc[self.p_datetime_col] if hasattr(row, "iloc") else None
        else:
            dt = None

        if dt is None:
            return math.nan

        if isinstance(dt, (pd.Timestamp, datetime)):
            if hasattr(dt, "to_pydatetime"):
                dt = dt.to_pydatetime()
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return date2num(dt)

        # Last resort: try to parse a string.
        if isinstance(dt, str):
            parsed = pd.Timestamp(dt)
            return date2num(parsed.to_pydatetime().replace(tzinfo=timezone.utc))

        return math.nan

    def _load(self) -> bool:
        if self._df_idx >= self._df_len:
            return False

        row = self._df.iloc[self._df_idx]
        idx = self._df.index[self._df_idx]
        self._df_idx += 1

        self.datetime[0] = self._resolve_datetime(row, idx)
        self.open[0] = self._resolve_col(self.p_open_col, row, idx)
        self.high[0] = self._resolve_col(self.p_high_col, row, idx)
        self.low[0] = self._resolve_col(self.p_low_col, row, idx)
        self.close[0] = self._resolve_col(self.p_close_col, row, idx)
        self.volume[0] = self._resolve_col(self.p_volume_col, row, idx)
        self.openinterest[0] = self._resolve_col(
            self.p_openinterest_col, row, idx
        )
        return True

    def stop(self) -> None:
        self._df = None  # type: ignore[assignment]
        super().stop()


# ── DataClone ────────────────────────────────────────────────────────────────


class DataClone(DataBase):
    """Lightweight clone that reads from another feed's lines.

    Does not re-read the source; instead copies line values from the
    original feed on each ``_load()`` call.
    """

    def __init__(self, source: DataBase, **kwargs: Any) -> None:
        # Inherit timeframe/compression from source if not overridden.
        kwargs.setdefault("timeframe", source.p_timeframe)
        kwargs.setdefault("compression", source.p_compression)
        super().__init__(**kwargs)
        self._source = source
        self._clone_idx = 0

    def _load(self) -> bool:
        src = self._source
        if self._clone_idx >= len(src):
            return False
        for i, name in enumerate(OHLC_LINES):
            self.get_line(i)[0] = src.get_line(i).get_absolute(self._clone_idx)
        self._clone_idx += 1
        return True


# ── DataFiller ───────────────────────────────────────────────────────────────


class DataFiller(DataBase):
    """Fills gaps in a data feed with synthetic bars.

    When a gap is detected (no bar for a calendar day), a bar is inserted
    with the previous bar's close used for O/H/L/C and volume=0.
    """

    def __init__(self, source: DataBase, fill_oi: bool = False, **kwargs: Any) -> None:
        kwargs.setdefault("timeframe", source.p_timeframe)
        kwargs.setdefault("compression", source.p_compression)
        super().__init__(**kwargs)
        self._source = source
        self._fill_oi = fill_oi
        self._last_bar: Optional[BarTuple] = None
        self._pending_fills: deque[BarTuple] = deque()
        self._src_idx = 0

    def _load(self) -> bool:
        # Serve pending fill bars first.
        if self._pending_fills:
            bar = self._pending_fills.popleft()
            _apply_bar(self, bar)
            return True

        src = self._source
        if self._src_idx >= len(src):
            return False

        # Read the next real bar.
        bar_vals = tuple(
            src.get_line(i).get_absolute(self._src_idx)
            for i in range(len(OHLC_LINES))
        )
        self._src_idx += 1

        if self._last_bar is not None:
            # Check for gap (difference > 1 day).
            gap_days = int(bar_vals[0] - self._last_bar[0])
            prev_close = self._last_bar[4]  # close
            oi = self._last_bar[6] if self._fill_oi else 0.0
            for d in range(1, gap_days):
                fill_dt = self._last_bar[0] + d
                fill_bar = (
                    fill_dt,
                    prev_close,
                    prev_close,
                    prev_close,
                    prev_close,
                    0.0,
                    oi,
                )
                self._pending_fills.append(fill_bar)

        self._last_bar = bar_vals
        _apply_bar(self, bar_vals)
        return True


# ── DataFilter ───────────────────────────────────────────────────────────────


class DataFilter(DataBase):
    """Abstract filter-based feed that wraps another feed.

    Subclasses override ``_filter_bar()`` to accept/reject bars.
    """

    def __init__(self, source: DataBase, **kwargs: Any) -> None:
        kwargs.setdefault("timeframe", source.p_timeframe)
        kwargs.setdefault("compression", source.p_compression)
        super().__init__(**kwargs)
        self._source = source
        self._src_idx = 0

    def _filter_bar(self) -> bool:
        """Return True to keep the bar, False to skip it."""
        return True

    def _load(self) -> bool:
        src = self._source
        while self._src_idx < len(src):
            for i in range(len(OHLC_LINES)):
                self.get_line(i)[0] = src.get_line(i).get_absolute(self._src_idx)
            self._src_idx += 1
            if self._filter_bar():
                return True
        return False
