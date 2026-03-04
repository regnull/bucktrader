"""DataSeries base classes and TimeFrame enumeration.

Defines the core time-indexed data abstractions used by all data feeds.
TimeFrame specifies bar granularity; DataSeries provides line-like storage;
OHLCDateTime bundles standard OHLCV + datetime lines.
"""

from __future__ import annotations

import enum
import math
from datetime import datetime, timezone
from typing import Optional

import numpy as np

# ── Date/Number conversions ──────────────────────────────────────────────────
# Matplotlib-style: float days since 0001-01-01 UTC, plus 1 (epoch day 1).
# We use a simpler epoch: days since 1970-01-01 (Unix epoch) for clarity.

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_SECONDS_PER_DAY = 86400.0


def date2num(dt: datetime) -> float:
    """Convert a datetime to a float (days since Unix epoch).

    If *dt* is timezone-naive it is assumed to be UTC.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = dt - _EPOCH
    return delta.total_seconds() / _SECONDS_PER_DAY


def num2date(num: float) -> datetime:
    """Convert a float (days since Unix epoch) back to a UTC datetime."""
    from datetime import timedelta

    return _EPOCH + timedelta(days=num)


# ── TimeFrame ────────────────────────────────────────────────────────────────


class TimeFrame(enum.IntEnum):
    """Bar granularity levels."""

    Ticks = 0
    MicroSeconds = 1
    Seconds = 2
    Minutes = 3
    Days = 4
    Weeks = 5
    Months = 6
    Years = 7
    NoTimeFrame = 8


# ── LineBuffer (standalone, lightweight) ─────────────────────────────────────
# Minimal line storage that will later be replaced by the full Lines system.

_DEFAULT_CAPACITY = 256


class LineBuffer:
    """A single time-indexed array of float64 values.

    Supports relative indexing: ``line[0]`` is the current value,
    ``line[-1]`` the previous, and so on.  Internally backed by a
    numpy array that grows as needed.
    """

    def __init__(self, name: str = "", initval: float = math.nan) -> None:
        self.name = name
        self._initval = initval
        self._array = np.full(_DEFAULT_CAPACITY, initval, dtype=np.float64)
        # _idx points at the *current* bar (the one most recently loaded).
        # -1 means no data has been loaded yet.
        self._idx: int = -1
        self._length: int = 0  # number of bars stored

    # ── capacity management ──────────────────────────────────────────────

    def _ensure_capacity(self, needed: int) -> None:
        if needed >= len(self._array):
            new_size = max(len(self._array) * 2, needed + 1)
            extended = np.full(new_size, self._initval, dtype=np.float64)
            extended[: len(self._array)] = self._array
            self._array = extended

    # ── public API ───────────────────────────────────────────────────────

    def forward(self) -> None:
        """Advance the pointer by one position (prepare to write new bar)."""
        self._idx += 1
        self._ensure_capacity(self._idx)
        self._array[self._idx] = self._initval
        self._length = max(self._length, self._idx + 1)

    def backwards(self) -> None:
        """Retract the pointer by one (used by replayer).

        Also shrinks the stored length if the retracted slot was the
        last element -- this ensures that a forward()/backwards() pair
        at the end of data does not inflate the reported length.
        """
        if self._idx >= 0:
            if self._idx + 1 == self._length:
                self._length -= 1
            self._idx -= 1

    def home(self) -> None:
        """Reset the pointer to the beginning."""
        self._idx = -1

    def advance(self, size: int = 1) -> None:
        """Move the pointer forward without writing a new bar."""
        self._idx += size

    def __getitem__(self, ago: int) -> float:
        """Relative access: ``line[0]`` = current, ``line[-1]`` = previous."""
        idx = self._idx + ago
        if idx < 0 or idx >= self._length:
            return self._initval
        return float(self._array[idx])

    def get(self, ago: int = 0, size: int = 1):
        """Return a rolling window ending at relative offset ``ago``.

        Missing historical values are filled with ``initval`` to preserve
        requested window length.
        """
        end_idx = self._idx + ago
        start_idx = end_idx - size + 1
        values = []
        for idx in range(start_idx, end_idx + 1):
            if 0 <= idx < self._length:
                values.append(float(self._array[idx]))
            else:
                values.append(self._initval)
        return values

    def __setitem__(self, ago: int, value: float) -> None:
        idx = self._idx + ago
        if idx < 0:
            raise IndexError(f"Cannot write to negative absolute index {idx}")
        self._ensure_capacity(idx)
        self._array[idx] = value
        self._length = max(self._length, idx + 1)

    def __len__(self) -> int:
        return self._length

    @property
    def array(self) -> np.ndarray:
        """Return a view of the stored data (only valid portion)."""
        return self._array[: self._length]

    @property
    def idx(self) -> int:
        return self._idx

    def get_absolute(self, idx: int) -> float:
        """Direct (absolute) index access."""
        if 0 <= idx < self._length:
            return float(self._array[idx])
        return self._initval


# ── DataSeries ───────────────────────────────────────────────────────────────


class DataSeries:
    """Base container for a collection of named LineBuffers.

    Subclasses declare ``_line_names`` to define which lines they contain.
    """

    _line_names: tuple[str, ...] = ()

    def __init__(self) -> None:
        self._lines: dict[str, LineBuffer] = {}
        for name in self._line_names:
            self._lines[name] = LineBuffer(name=name)

    # ── line access ──────────────────────────────────────────────────────

    def __getattr__(self, name: str) -> LineBuffer:
        # Provide attribute-style access to lines: series.close, etc.
        if name.startswith("_"):
            raise AttributeError(name)
        lines = self.__dict__.get("_lines")
        if lines is not None and name in lines:
            return lines[name]
        raise AttributeError(
            f"'{type(self).__name__}' has no line '{name}'"
        )

    def get_line(self, index: int) -> LineBuffer:
        """Return a line by its positional index."""
        return self._lines[self._line_names[index]]

    def get_line_by_name(self, name: str) -> LineBuffer:
        """Return a line by name."""
        return self._lines[name]

    @property
    def line_names(self) -> tuple[str, ...]:
        return self._line_names

    @property
    def lines(self) -> "DataSeries":
        """Return self so that ``data.lines.close[0]`` works."""
        return self

    # ── pointer management ───────────────────────────────────────────────

    def forward(self) -> None:
        """Advance all line pointers by one."""
        for line in self._lines.values():
            line.forward()

    def backwards(self) -> None:
        """Retract all line pointers by one."""
        for line in self._lines.values():
            line.backwards()

    def home(self) -> None:
        """Reset all line pointers to the beginning."""
        for line in self._lines.values():
            line.home()

    def advance(self, size: int = 1) -> None:
        """Move all pointers forward without writing."""
        for line in self._lines.values():
            line.advance(size)

    def __len__(self) -> int:
        if not self._lines:
            return 0
        first_line = next(iter(self._lines.values()))
        return len(first_line)


# ── OHLCDateTime ─────────────────────────────────────────────────────────────

# Standard line names in canonical order.
OHLC_LINES = (
    "datetime",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "openinterest",
)


class OHLCDateTime(DataSeries):
    """DataSeries with the standard OHLCV + datetime lines.

    Line indices:
        0 - datetime   (float, days since epoch)
        1 - open
        2 - high
        3 - low
        4 - close
        5 - volume
        6 - openinterest
    """

    _line_names = OHLC_LINES
