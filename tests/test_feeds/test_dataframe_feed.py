"""Tests for DataFrameData (pandas DataFrame data feed)."""

from __future__ import annotations

import math
from datetime import datetime, timezone

import pandas as pd
import pytest

from bucktrader.dataseries import date2num, num2date
from bucktrader.feed import DataFrameData

from .conftest import NUM_ROWS


# ── DataFrame with DatetimeIndex ─────────────────────────────────────────────


class TestDataFrameWithIndex:
    """DataFrame where datetime comes from the index."""

    def test_load_all_rows(self, sample_dataframe: pd.DataFrame) -> None:
        feed = DataFrameData(
            dataname=sample_dataframe,
            datetime_col=None,  # use index
            openinterest_col="OI",
        )
        feed.start()
        count = 0
        while feed.load():
            count += 1
        feed.stop()
        assert count == NUM_ROWS

    def test_first_bar_values(self, sample_dataframe: pd.DataFrame) -> None:
        feed = DataFrameData(
            dataname=sample_dataframe,
            datetime_col=None,
            openinterest_col="OI",
        )
        feed.start()
        assert feed.load() is True

        expected_dt = date2num(datetime(2024, 1, 2, tzinfo=timezone.utc))
        assert feed.datetime[0] == pytest.approx(expected_dt)
        assert feed.open[0] == pytest.approx(100.0)
        assert feed.high[0] == pytest.approx(102.5)
        assert feed.low[0] == pytest.approx(99.5)
        assert feed.close[0] == pytest.approx(101.0)
        assert feed.volume[0] == pytest.approx(10000.0)
        assert feed.openinterest[0] == pytest.approx(500.0)
        feed.stop()

    def test_preload(self, sample_dataframe: pd.DataFrame) -> None:
        feed = DataFrameData(
            dataname=sample_dataframe,
            datetime_col=None,
            openinterest_col="OI",
        )
        feed.start()
        feed.preload()
        assert len(feed) == NUM_ROWS
        feed.stop()


# ── DataFrame with Date column ───────────────────────────────────────────────


class TestDataFrameWithDateColumn:
    """DataFrame where datetime comes from a named column."""

    def test_load_all_rows(
        self, sample_dataframe_with_date_col: pd.DataFrame
    ) -> None:
        feed = DataFrameData(
            dataname=sample_dataframe_with_date_col,
            datetime_col="Date",
            openinterest_col=None,
        )
        feed.start()
        count = 0
        while feed.load():
            count += 1
        feed.stop()
        assert count == NUM_ROWS

    def test_no_openinterest(
        self, sample_dataframe_with_date_col: pd.DataFrame
    ) -> None:
        feed = DataFrameData(
            dataname=sample_dataframe_with_date_col,
            datetime_col="Date",
            openinterest_col=None,
        )
        feed.start()
        assert feed.load() is True
        assert math.isnan(feed.openinterest[0])
        feed.stop()


# ── Column mapping by integer index ─────────────────────────────────────────


class TestDataFrameColumnByIndex:
    """Map columns by integer position instead of name."""

    def test_integer_column_mapping(
        self, sample_dataframe_with_date_col: pd.DataFrame
    ) -> None:
        # Columns: Date(0), Open(1), High(2), Low(3), Close(4), Volume(5)
        feed = DataFrameData(
            dataname=sample_dataframe_with_date_col,
            datetime_col=0,
            open_col=1,
            high_col=2,
            low_col=3,
            close_col=4,
            volume_col=5,
            openinterest_col=None,
        )
        feed.start()
        assert feed.load() is True
        assert feed.open[0] == pytest.approx(100.0)
        assert feed.close[0] == pytest.approx(101.0)
        feed.stop()


# ── Date filters ─────────────────────────────────────────────────────────────


class TestDataFrameDateFilters:
    """Test fromdate/todate with DataFrame feeds."""

    def test_fromdate(self, sample_dataframe: pd.DataFrame) -> None:
        from_dt = datetime(2024, 1, 15, tzinfo=timezone.utc)
        feed = DataFrameData(
            dataname=sample_dataframe,
            datetime_col=None,
            openinterest_col="OI",
            fromdate=from_dt,
        )
        feed.start()
        count = 0
        while feed.load():
            bar_dt = num2date(feed.datetime[0])
            assert bar_dt >= from_dt
            count += 1
        feed.stop()
        assert count > 0
        assert count < NUM_ROWS


# ── Error handling ───────────────────────────────────────────────────────────


class TestDataFrameErrors:
    """Test error cases."""

    def test_non_dataframe_raises(self) -> None:
        feed = DataFrameData(dataname="not_a_dataframe")
        with pytest.raises(TypeError, match="pandas DataFrame"):
            feed.start()
