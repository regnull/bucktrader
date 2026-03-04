"""Tests for CSV-based data feeds (CSVDataBase, GenericCSVData)."""

from __future__ import annotations

import io
import math
from datetime import datetime, timezone
from pathlib import Path

import pytest

from bucktrader.dataseries import TimeFrame, date2num, num2date
from bucktrader.feed import GenericCSVData

from .conftest import NUM_ROWS


# ── GenericCSVData from file ─────────────────────────────────────────────────


class TestGenericCSVDataFromFile:
    """Load sample CSV from a file path."""

    def test_load_all_rows(self, sample_csv_file: Path) -> None:
        feed = GenericCSVData(
            dataname=sample_csv_file,
            dtformat="%Y-%m-%d",
            openinterest_col=6,
        )
        feed.start()
        count = 0
        while feed.load():
            count += 1
        feed.stop()
        assert count == NUM_ROWS

    def test_first_bar_values(self, sample_csv_file: Path) -> None:
        feed = GenericCSVData(
            dataname=sample_csv_file,
            dtformat="%Y-%m-%d",
            openinterest_col=6,
        )
        feed.start()
        assert feed.load() is True

        expected_dt = date2num(
            datetime(2024, 1, 2, tzinfo=timezone.utc)
        )
        assert feed.datetime[0] == pytest.approx(expected_dt)
        assert feed.open[0] == pytest.approx(100.0)
        assert feed.high[0] == pytest.approx(102.5)
        assert feed.low[0] == pytest.approx(99.5)
        assert feed.close[0] == pytest.approx(101.0)
        assert feed.volume[0] == pytest.approx(10000.0)
        assert feed.openinterest[0] == pytest.approx(500.0)
        feed.stop()

    def test_last_bar_values(self, sample_csv_file: Path) -> None:
        feed = GenericCSVData(
            dataname=sample_csv_file,
            dtformat="%Y-%m-%d",
            openinterest_col=6,
        )
        feed.start()
        while feed.load():
            pass
        # After load() returns False, the last valid bar is at [0].
        # Actually, after final load() returns False, the pointer was
        # retracted by backwards(). The last successfully loaded bar
        # should be accessible.
        assert feed.close[0] == pytest.approx(120.0)
        feed.stop()

    def test_preload(self, sample_csv_file: Path) -> None:
        feed = GenericCSVData(
            dataname=sample_csv_file,
            dtformat="%Y-%m-%d",
            openinterest_col=6,
        )
        feed.start()
        feed.preload()
        # After preload, length should match row count.
        assert len(feed) == NUM_ROWS
        # Pointer is at home (-1). Use advance() to step through
        # pre-loaded data without overwriting stored values.
        feed.advance(1)  # idx now at 0
        assert feed.open[0] == pytest.approx(100.0)
        assert feed.close[0] == pytest.approx(101.0)
        # Verify last bar is accessible by absolute index.
        assert feed.close.get_absolute(NUM_ROWS - 1) == pytest.approx(120.0)
        feed.stop()


# ── GenericCSVData from StringIO ─────────────────────────────────────────────


class TestGenericCSVDataFromIO:
    """Load from a file-like object."""

    def test_load_from_stringio(self, sample_csv_io: io.StringIO) -> None:
        feed = GenericCSVData(
            dataname=sample_csv_io,
            dtformat="%Y-%m-%d",
            openinterest_col=6,
        )
        feed.start()
        count = 0
        while feed.load():
            count += 1
        feed.stop()
        assert count == NUM_ROWS


# ── Column mapping ───────────────────────────────────────────────────────────


class TestCSVColumnMapping:
    """Test that column index mapping works correctly."""

    def test_no_openinterest(self, sample_csv_no_oi_file: Path) -> None:
        feed = GenericCSVData(
            dataname=sample_csv_no_oi_file,
            dtformat="%Y-%m-%d",
            openinterest_col=-1,  # not present
        )
        feed.start()
        assert feed.load() is True
        assert math.isnan(feed.openinterest[0])
        feed.stop()


# ── Date filters ─────────────────────────────────────────────────────────────


class TestCSVDateFilters:
    """Test fromdate / todate filtering."""

    def test_fromdate(self, sample_csv_file: Path) -> None:
        from_dt = datetime(2024, 1, 15, tzinfo=timezone.utc)
        feed = GenericCSVData(
            dataname=sample_csv_file,
            dtformat="%Y-%m-%d",
            openinterest_col=6,
            fromdate=from_dt,
        )
        feed.start()
        count = 0
        while feed.load():
            # Every loaded bar should be on or after Jan 15.
            bar_dt = num2date(feed.datetime[0])
            assert bar_dt >= from_dt
            count += 1
        feed.stop()
        assert count > 0
        assert count < NUM_ROWS

    def test_todate(self, sample_csv_file: Path) -> None:
        to_dt = datetime(2024, 1, 15, tzinfo=timezone.utc)
        feed = GenericCSVData(
            dataname=sample_csv_file,
            dtformat="%Y-%m-%d",
            openinterest_col=6,
            todate=to_dt,
        )
        feed.start()
        count = 0
        while feed.load():
            bar_dt = num2date(feed.datetime[0])
            assert bar_dt <= to_dt
            count += 1
        feed.stop()
        assert count > 0
        assert count < NUM_ROWS

    def test_fromdate_and_todate(self, sample_csv_file: Path) -> None:
        from_dt = datetime(2024, 1, 10, tzinfo=timezone.utc)
        to_dt = datetime(2024, 1, 20, tzinfo=timezone.utc)
        feed = GenericCSVData(
            dataname=sample_csv_file,
            dtformat="%Y-%m-%d",
            openinterest_col=6,
            fromdate=from_dt,
            todate=to_dt,
        )
        feed.start()
        count = 0
        while feed.load():
            bar_dt = num2date(feed.datetime[0])
            assert from_dt <= bar_dt <= to_dt
            count += 1
        feed.stop()
        assert count > 0


# ── Custom dtformat callable ─────────────────────────────────────────────────


class TestCSVCustomDateParser:
    """Test using a callable for dtformat."""

    def test_callable_dtformat(self, sample_csv_file: Path) -> None:
        def my_parser(s: str) -> datetime:
            return datetime.strptime(s, "%Y-%m-%d")

        feed = GenericCSVData(
            dataname=sample_csv_file,
            dtformat=my_parser,
            openinterest_col=6,
        )
        feed.start()
        assert feed.load() is True
        assert feed.open[0] == pytest.approx(100.0)
        feed.stop()


# ── Edge cases ───────────────────────────────────────────────────────────────


class TestCSVEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_csv(self, tmp_path: Path) -> None:
        p = tmp_path / "empty.csv"
        p.write_text("Date,Open,High,Low,Close,Volume\n")
        feed = GenericCSVData(
            dataname=p,
            dtformat="%Y-%m-%d",
            openinterest_col=-1,
        )
        feed.start()
        assert feed.load() is False
        feed.stop()

    def test_invalid_dataname(self) -> None:
        feed = GenericCSVData(dataname=12345)
        with pytest.raises(ValueError, match="filename or file-like"):
            feed.start()

    def test_parameters_stored(self, sample_csv_file: Path) -> None:
        feed = GenericCSVData(
            dataname=sample_csv_file,
            name="test_feed",
            compression=5,
            timeframe=TimeFrame.Minutes,
        )
        assert feed.p_name == "test_feed"
        assert feed.p_compression == 5
        assert feed.p_timeframe == TimeFrame.Minutes
