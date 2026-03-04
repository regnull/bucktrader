"""Writer system for outputting strategy data to files or stdout.

WriterBase  -- Abstract interface for writers.
WriterFile  -- CSV-formatted output with configurable separator,
               NaN filtering, bar counter, and rounding.
"""

from __future__ import annotations

import math
import sys
from typing import Any, TextIO


class WriterBase:
    """Abstract base class for writers.

    Writers output strategy data (prices, indicators, observers, analyzers)
    to files or stdout in a structured format.
    """

    def start(self) -> None:
        """Open output file/stream."""

    def stop(self) -> None:
        """Close output file/stream."""

    def addheaders(self, headers: list[str]) -> None:
        """Receive column headers."""

    def next(self, values: list[Any]) -> None:
        """Called each bar -- write current values."""


class WriterFile(WriterBase):
    """CSV writer that outputs data to a file or stream.

    Params:
        out           -- output stream (default: sys.stdout)
        close_out     -- close the output stream when done (default: False)
        csv           -- enable CSV value output (default: True)
        csvsep        -- CSV separator (default: ",")
        csv_filternan -- replace NaN with empty string (default: True)
        csv_counter   -- include bar counter column (default: True)
        indent        -- indentation for section headers (default: 2)
        separators    -- add separator lines between sections (default: True)
        rounding      -- decimal places for rounding (default: None)
    """

    def __init__(
        self,
        out: TextIO | None = None,
        close_out: bool = False,
        csv: bool = True,
        csvsep: str = ",",
        csv_filternan: bool = True,
        csv_counter: bool = True,
        indent: int = 2,
        separators: bool = True,
        rounding: int | None = None,
    ) -> None:
        self.out = out if out is not None else sys.stdout
        self.close_out = close_out
        self.csv = csv
        self.csvsep = csvsep
        self.csv_filternan = csv_filternan
        self.csv_counter = csv_counter
        self.indent = indent
        self.separators = separators
        self.rounding = rounding

        self._headers: list[str] = []
        self._bar_count: int = 0

    def start(self) -> None:
        """Initialize the writer."""
        self._bar_count = 0

    def stop(self) -> None:
        """Close the output stream if configured to do so."""
        if self.close_out and self.out is not None:
            try:
                self.out.close()
            except (AttributeError, IOError):
                pass

    def addheaders(self, headers: list[str]) -> None:
        """Receive and write column headers."""
        self._headers = list(headers)

        if not self.csv:
            return

        parts = []
        if self.csv_counter:
            parts.append("bar")

        parts.extend(self._headers)

        line = self.csvsep.join(parts)
        self.out.write(line + "\n")

    def next(self, values: list[Any]) -> None:
        """Write one bar of data."""
        if not self.csv:
            return

        self._bar_count += 1

        parts = []
        if self.csv_counter:
            parts.append(str(self._bar_count))

        for val in values:
            parts.append(self._format_value(val))

        line = self.csvsep.join(parts)
        self.out.write(line + "\n")

    def write_section(self, title: str, content: str = "") -> None:
        """Write a section header with optional content."""
        if self.separators:
            self.out.write("=" * 40 + "\n")

        prefix = " " * self.indent
        self.out.write(f"{prefix}{title}\n")

        if content:
            self.out.write(f"{prefix}{content}\n")

        if self.separators:
            self.out.write("-" * 40 + "\n")

    def _format_value(self, val: Any) -> str:
        """Format a single value for CSV output."""
        if val is None:
            return "" if self.csv_filternan else "None"

        if isinstance(val, float):
            if math.isnan(val):
                return "" if self.csv_filternan else "nan"
            if self.rounding is not None:
                return str(round(val, self.rounding))
            return str(val)

        return str(val)
