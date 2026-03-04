"""Tests for TimeFrame enum, LineBuffer, DataSeries, and OHLCDateTime."""

from __future__ import annotations

import math

import numpy as np
import pytest

from bucktrader.dataseries import (
    DataSeries,
    LineBuffer,
    OHLCDateTime,
    TimeFrame,
    date2num,
    num2date,
)


# ── TimeFrame ────────────────────────────────────────────────────────────────


class TestTimeFrame:
    """Verify TimeFrame enum values and ordering."""

    def test_enum_values(self) -> None:
        assert TimeFrame.Ticks == 0
        assert TimeFrame.MicroSeconds == 1
        assert TimeFrame.Seconds == 2
        assert TimeFrame.Minutes == 3
        assert TimeFrame.Days == 4
        assert TimeFrame.Weeks == 5
        assert TimeFrame.Months == 6
        assert TimeFrame.Years == 7
        assert TimeFrame.NoTimeFrame == 8

    def test_ordering(self) -> None:
        assert TimeFrame.Ticks < TimeFrame.Days
        assert TimeFrame.Minutes < TimeFrame.Weeks
        assert TimeFrame.Days < TimeFrame.Years

    def test_all_members_present(self) -> None:
        assert len(TimeFrame) == 9


# ── date2num / num2date ──────────────────────────────────────────────────────


class TestDateConversion:
    """Verify round-trip datetime <-> float conversion."""

    def test_round_trip(self) -> None:
        from datetime import datetime, timezone

        dt = datetime(2024, 6, 15, 12, 30, 0, tzinfo=timezone.utc)
        num = date2num(dt)
        recovered = num2date(num)
        # Allow sub-second tolerance.
        assert abs((recovered - dt).total_seconds()) < 1.0

    def test_epoch(self) -> None:
        from datetime import datetime, timezone

        epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
        assert date2num(epoch) == 0.0

    def test_naive_datetime_treated_as_utc(self) -> None:
        from datetime import datetime, timezone

        naive = datetime(2024, 1, 1)
        aware = datetime(2024, 1, 1, tzinfo=timezone.utc)
        assert date2num(naive) == date2num(aware)


# ── LineBuffer ───────────────────────────────────────────────────────────────


class TestLineBuffer:
    """Test the standalone line storage."""

    def test_forward_and_write(self) -> None:
        lb = LineBuffer(name="close")
        lb.forward()
        lb[0] = 100.0
        assert lb[0] == 100.0
        assert len(lb) == 1

    def test_relative_indexing(self) -> None:
        lb = LineBuffer()
        lb.forward()
        lb[0] = 10.0
        lb.forward()
        lb[0] = 20.0
        lb.forward()
        lb[0] = 30.0
        assert lb[0] == 30.0
        assert lb[-1] == 20.0
        assert lb[-2] == 10.0

    def test_out_of_range_returns_nan(self) -> None:
        lb = LineBuffer()
        lb.forward()
        lb[0] = 5.0
        assert math.isnan(lb[-1])  # no previous bar

    def test_backwards(self) -> None:
        lb = LineBuffer()
        lb.forward()
        lb[0] = 1.0
        lb.forward()
        lb[0] = 2.0
        lb.backwards()
        assert lb[0] == 1.0

    def test_home(self) -> None:
        lb = LineBuffer()
        for i in range(5):
            lb.forward()
            lb[0] = float(i)
        lb.home()
        assert lb.idx == -1

    def test_array_property(self) -> None:
        lb = LineBuffer()
        for v in [10.0, 20.0, 30.0]:
            lb.forward()
            lb[0] = v
        np.testing.assert_array_equal(lb.array, [10.0, 20.0, 30.0])

    def test_get_absolute(self) -> None:
        lb = LineBuffer()
        lb.forward()
        lb[0] = 42.0
        lb.forward()
        lb[0] = 99.0
        assert lb.get_absolute(0) == 42.0
        assert lb.get_absolute(1) == 99.0
        assert math.isnan(lb.get_absolute(5))

    def test_grow_capacity(self) -> None:
        lb = LineBuffer()
        for i in range(500):
            lb.forward()
            lb[0] = float(i)
        assert len(lb) == 500
        assert lb[0] == 499.0


# ── DataSeries ───────────────────────────────────────────────────────────────


class TestDataSeries:
    """Test DataSeries multi-line container."""

    def test_custom_lines(self) -> None:
        class MySeries(DataSeries):
            _line_names = ("alpha", "beta")

        s = MySeries()
        s.forward()
        s.alpha[0] = 1.0
        s.beta[0] = 2.0
        assert s.alpha[0] == 1.0
        assert s.beta[0] == 2.0

    def test_get_line_by_index(self) -> None:
        class MySeries(DataSeries):
            _line_names = ("x", "y", "z")

        s = MySeries()
        assert s.get_line(0).name == "x"
        assert s.get_line(2).name == "z"

    def test_get_line_by_name(self) -> None:
        class MySeries(DataSeries):
            _line_names = ("x", "y")

        s = MySeries()
        assert s.get_line_by_name("y").name == "y"

    def test_forward_all_lines(self) -> None:
        class MySeries(DataSeries):
            _line_names = ("a", "b")

        s = MySeries()
        s.forward()
        s.a[0] = 10.0
        s.b[0] = 20.0
        s.forward()
        s.a[0] = 11.0
        s.b[0] = 21.0
        assert s.a[-1] == 10.0
        assert s.b[-1] == 20.0

    def test_home_resets_all(self) -> None:
        class MySeries(DataSeries):
            _line_names = ("a",)

        s = MySeries()
        s.forward()
        s.a[0] = 1.0
        s.home()
        assert s.a.idx == -1

    def test_len(self) -> None:
        class MySeries(DataSeries):
            _line_names = ("a",)

        s = MySeries()
        assert len(s) == 0
        s.forward()
        s.a[0] = 1.0
        assert len(s) == 1

    def test_invalid_line_raises(self) -> None:
        class MySeries(DataSeries):
            _line_names = ("a",)

        s = MySeries()
        with pytest.raises(AttributeError, match="no line"):
            _ = s.nonexistent


# ── OHLCDateTime ─────────────────────────────────────────────────────────────


class TestOHLCDateTime:
    """Test the standard OHLCV + datetime line set."""

    def test_has_all_standard_lines(self) -> None:
        ohlc = OHLCDateTime()
        expected = (
            "datetime",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "openinterest",
        )
        assert ohlc.line_names == expected

    def test_line_indices(self) -> None:
        ohlc = OHLCDateTime()
        assert ohlc.get_line(0).name == "datetime"
        assert ohlc.get_line(1).name == "open"
        assert ohlc.get_line(4).name == "close"
        assert ohlc.get_line(6).name == "openinterest"

    def test_write_and_read(self) -> None:
        ohlc = OHLCDateTime()
        ohlc.forward()
        ohlc.datetime[0] = 19723.0  # ~2024-01-01
        ohlc.open[0] = 100.0
        ohlc.high[0] = 105.0
        ohlc.low[0] = 98.0
        ohlc.close[0] = 103.0
        ohlc.volume[0] = 50000.0
        ohlc.openinterest[0] = 1000.0

        assert ohlc.open[0] == 100.0
        assert ohlc.close[0] == 103.0
        assert ohlc.volume[0] == 50000.0

    def test_lines_alias(self) -> None:
        ohlc = OHLCDateTime()
        ohlc.forward()
        ohlc.lines.close[0] = 42.0
        assert ohlc.close[0] == 42.0
