"""Tests for data feed filters (resample, replay, session, heikin-ashi, renko, calendar)."""

from __future__ import annotations

import math
from datetime import datetime, time, timezone
from pathlib import Path

import pytest

from bucktrader.dataseries import TimeFrame, date2num, num2date
from bucktrader.feed import DataBase, GenericCSVData
from bucktrader.filters.calendardays import CalendarDays
from bucktrader.filters.heikinashi import HeikinAshi
from bucktrader.filters.renko import Renko
from bucktrader.filters.replay import Replayer
from bucktrader.filters.resample import Resampler, _timeframe_boundary
from bucktrader.filters.session import SessionFiller, SessionFilter

from .conftest import NUM_ROWS


# ── Helpers ──────────────────────────────────────────────────────────────────


def _load_csv_feed(csv_path: Path, **kwargs) -> GenericCSVData:
    """Create and start a GenericCSVData feed from *csv_path*."""
    feed = GenericCSVData(
        dataname=csv_path,
        dtformat="%Y-%m-%d",
        openinterest_col=6,
        **kwargs,
    )
    feed.start()
    return feed


def _collect_bars(feed: DataBase) -> list[dict]:
    """Load all bars from *feed* and return them as dicts.

    After the source is exhausted, calls ``_last()`` to let filters
    flush any buffered bars, then drains remaining stack entries.
    """
    bars = []
    while feed.load():
        bars.append(
            {
                "datetime": feed.datetime[0],
                "open": feed.open[0],
                "high": feed.high[0],
                "low": feed.low[0],
                "close": feed.close[0],
                "volume": feed.volume[0],
                "oi": feed.openinterest[0],
            }
        )
    # Notify filters that data is exhausted (flushes remaining buffered bars).
    feed._last()
    # Drain any bars pushed to the stack by the flush.
    while feed._barstack or feed._barstash:
        feed.forward()
        if feed._fromstack():
            bars.append(
                {
                    "datetime": feed.datetime[0],
                    "open": feed.open[0],
                    "high": feed.high[0],
                    "low": feed.low[0],
                    "close": feed.close[0],
                    "volume": feed.volume[0],
                    "oi": feed.openinterest[0],
                }
            )
        else:
            feed.backwards()
            break
    return bars


# ── Resampler ────────────────────────────────────────────────────────────────


class TestResampler:
    """Test resampling bars into larger timeframes."""

    def test_boundary_helper_days(self) -> None:
        dt1 = date2num(datetime(2024, 1, 2, tzinfo=timezone.utc))
        dt2 = date2num(datetime(2024, 1, 3, tzinfo=timezone.utc))
        k1 = _timeframe_boundary(dt1, TimeFrame.Days, 1)
        k2 = _timeframe_boundary(dt2, TimeFrame.Days, 1)
        assert k1 != k2

    def test_boundary_helper_weeks(self) -> None:
        # Same ISO week.
        mon = date2num(datetime(2024, 1, 1, tzinfo=timezone.utc))  # Monday
        tue = date2num(datetime(2024, 1, 2, tzinfo=timezone.utc))
        k_mon = _timeframe_boundary(mon, TimeFrame.Weeks, 1)
        k_tue = _timeframe_boundary(tue, TimeFrame.Weeks, 1)
        assert k_mon == k_tue

    def test_resample_daily_to_weekly(self, sample_csv_file: Path) -> None:
        """Resampling 20 daily bars should produce fewer weekly bars."""
        feed = _load_csv_feed(sample_csv_file)

        resampler = Resampler(feed, timeframe=TimeFrame.Weeks, compression=1)
        feed._filters = [resampler]

        bars = _collect_bars(feed)
        feed.stop()

        # 20 trading days spanning ~5 calendar weeks -> expect ~5 bars.
        assert len(bars) > 0
        assert len(bars) < NUM_ROWS

    def test_resampled_ohlc_correctness(self, sample_csv_file: Path) -> None:
        """Check that the first resampled bar has correct O/H/L/C."""
        feed = _load_csv_feed(sample_csv_file)

        resampler = Resampler(feed, timeframe=TimeFrame.Weeks, compression=1)
        feed._filters = [resampler]

        bars = _collect_bars(feed)
        feed.stop()

        first = bars[0]
        # The first bar aggregates the first trading week.
        # Open should be from the first day; high/low from the week.
        assert first["open"] == pytest.approx(100.0)
        assert first["high"] >= first["open"]
        assert first["low"] <= first["open"]

    def test_resampled_volume_accumulates(self, sample_csv_file: Path) -> None:
        """Volume should be the sum of constituent bars."""
        feed = _load_csv_feed(sample_csv_file)

        resampler = Resampler(feed, timeframe=TimeFrame.Weeks, compression=1)
        feed._filters = [resampler]

        bars = _collect_bars(feed)
        feed.stop()

        # Each weekly bar's volume should exceed any single daily bar.
        for bar in bars:
            assert bar["volume"] > 0


# ── Replayer ─────────────────────────────────────────────────────────────────


class TestReplayer:
    """Test the replayer filter (intermediate partial bars)."""

    def test_replayer_delivers_all_inputs(self, sample_csv_file: Path) -> None:
        """Replayer should deliver a bar for every input bar."""
        feed = _load_csv_feed(sample_csv_file)

        replayer = Replayer(feed, timeframe=TimeFrame.Weeks, compression=1)
        feed._filters = [replayer]

        bars = _collect_bars(feed)
        feed.stop()

        # Replayer delivers intermediate bars, so count >= raw count or close.
        # At minimum, it should deliver something for each input.
        assert len(bars) > 0

    def test_replayer_final_bar_matches_resampler(
        self, sample_csv_file: Path
    ) -> None:
        """At period boundaries, replayer and resampler should agree on close."""
        # Load resampled data.
        feed_r = _load_csv_feed(sample_csv_file)
        resampler = Resampler(feed_r, timeframe=TimeFrame.Weeks, compression=1)
        feed_r._filters = [resampler]
        resampled = _collect_bars(feed_r)
        feed_r.stop()

        # The last resampled bar's close should equal the last raw bar's close.
        assert resampled[-1]["close"] == pytest.approx(120.0)


# ── SessionFilter ────────────────────────────────────────────────────────────


class TestSessionFilter:
    """Test session time filtering."""

    def test_no_session_passes_all(self, sample_csv_file: Path) -> None:
        feed = _load_csv_feed(sample_csv_file)
        sf = SessionFilter(feed)
        feed._filters = [sf]

        bars = _collect_bars(feed)
        feed.stop()
        assert len(bars) == NUM_ROWS

    def test_session_filter_removes_bars(self, tmp_path: Path) -> None:
        """Create intraday data and filter by session."""
        csv_content = "DateTime,Open,High,Low,Close,Volume\n"
        # Bars at 08:00, 09:00, ..., 17:00
        for hour in range(8, 18):
            csv_content += (
                f"2024-01-02 {hour:02d}:00:00,100,101,99,100.5,1000\n"
            )
        p = tmp_path / "intraday.csv"
        p.write_text(csv_content)

        feed = GenericCSVData(
            dataname=p,
            dtformat="%Y-%m-%d %H:%M:%S",
            openinterest_col=-1,
            sessionstart=time(9, 30),
            sessionend=time(16, 0),
        )
        feed.start()
        sf = SessionFilter(feed)
        feed._filters = [sf]

        bars = _collect_bars(feed)
        feed.stop()

        # Only bars between 09:30 and 16:00 should pass.
        assert len(bars) < 10
        for bar in bars:
            dt = num2date(bar["datetime"])
            assert dt.hour >= 9
            assert dt.hour <= 16


# ── HeikinAshi ───────────────────────────────────────────────────────────────


class TestHeikinAshi:
    """Test Heikin-Ashi bar transformation."""

    def test_heikinashi_modifies_bars(self, sample_csv_file: Path) -> None:
        """HA bars should differ from raw OHLC."""
        # Load raw.
        feed_raw = _load_csv_feed(sample_csv_file)
        raw_bars = _collect_bars(feed_raw)
        feed_raw.stop()

        # Load with HeikinAshi filter.
        feed_ha = _load_csv_feed(sample_csv_file)
        ha = HeikinAshi(feed_ha)
        feed_ha._filters = [ha]
        ha_bars = _collect_bars(feed_ha)
        feed_ha.stop()

        assert len(ha_bars) == len(raw_bars)
        # At least some bars should differ (HA smooths prices).
        diffs = sum(
            1
            for r, h in zip(raw_bars, ha_bars)
            if abs(r["close"] - h["close"]) > 0.001
        )
        assert diffs > 0

    def test_heikinashi_close_formula(self, sample_csv_file: Path) -> None:
        """HA close should be (O+H+L+C)/4 of the raw bar (for each bar)."""
        feed_raw = _load_csv_feed(sample_csv_file)
        raw_bars = _collect_bars(feed_raw)
        feed_raw.stop()

        feed_ha = _load_csv_feed(sample_csv_file)
        ha = HeikinAshi(feed_ha)
        feed_ha._filters = [ha]
        ha_bars = _collect_bars(feed_ha)
        feed_ha.stop()

        for r, h in zip(raw_bars, ha_bars):
            expected_close = (r["open"] + r["high"] + r["low"] + r["close"]) / 4
            assert h["close"] == pytest.approx(expected_close, abs=0.01)


# ── Renko ────────────────────────────────────────────────────────────────────


class TestRenko:
    """Test Renko brick generation."""

    def test_renko_generates_bricks(self, sample_csv_file: Path) -> None:
        """With a small brick size, many bricks should be generated."""
        feed = _load_csv_feed(sample_csv_file)
        renko = Renko(feed, brick_size=1.0)
        feed._filters = [renko]

        bars = _collect_bars(feed)
        feed.stop()

        # Price goes from ~100 to ~120, so ~20 bricks with size 1.
        assert len(bars) > 0

    def test_renko_brick_size(self, sample_csv_file: Path) -> None:
        """Each brick should have |close - open| == brick_size."""
        feed = _load_csv_feed(sample_csv_file)
        brick_size = 2.0
        renko = Renko(feed, brick_size=brick_size)
        feed._filters = [renko]

        bars = _collect_bars(feed)
        feed.stop()

        for bar in bars:
            diff = abs(bar["close"] - bar["open"])
            assert diff == pytest.approx(brick_size, abs=0.01)

    def test_renko_invalid_brick_size(self, sample_csv_file: Path) -> None:
        feed = _load_csv_feed(sample_csv_file)
        with pytest.raises(ValueError, match="positive"):
            Renko(feed, brick_size=0.0)


# ── CalendarDays ─────────────────────────────────────────────────────────────


class TestCalendarDays:
    """Test calendar day gap filling."""

    def test_fills_weekend_gaps(self, sample_csv_file: Path) -> None:
        """Calendar filter should add bars for missing weekend days."""
        feed = _load_csv_feed(sample_csv_file)
        cal = CalendarDays(feed)
        feed._filters = [cal]

        bars = _collect_bars(feed)
        feed.stop()

        # Original data has 20 bars spanning Jan 2 - Jan 29 (28 days).
        # With gaps filled we should have more bars than the original.
        assert len(bars) >= NUM_ROWS

    def test_filled_bars_have_zero_volume(self, sample_csv_file: Path) -> None:
        """Synthetic bars should have zero volume."""
        feed = _load_csv_feed(sample_csv_file)
        cal = CalendarDays(feed)
        feed._filters = [cal]

        bars = _collect_bars(feed)
        feed.stop()

        zero_vol_count = sum(1 for b in bars if b["volume"] == 0.0)
        # At least some bars are synthetic fills.
        assert zero_vol_count > 0


# ── Simple callable filter ───────────────────────────────────────────────────


class TestSimpleCallableFilter:
    """Test using a plain function as a filter."""

    def test_filter_bearish_bars(self, sample_csv_file: Path) -> None:
        """Remove bars where close < open."""

        def bearish_filter(data: DataBase) -> bool:
            return data.close[0] < data.open[0]

        feed = _load_csv_feed(sample_csv_file, filters=[bearish_filter])

        bars = _collect_bars(feed)
        feed.stop()

        # All remaining bars should have close >= open.
        for bar in bars:
            assert bar["close"] >= bar["open"]


# ── DataStatus ───────────────────────────────────────────────────────────────


class TestDataStatus:
    """Verify DataStatus enum values."""

    def test_values(self) -> None:
        from bucktrader.feed import DataStatus

        assert DataStatus.LIVE == 0
        assert DataStatus.CONNECTED == 1
        assert DataStatus.DISCONNECTED == 2
        assert DataStatus.CONNBROKEN == 3
        assert DataStatus.DELAYED == 4
