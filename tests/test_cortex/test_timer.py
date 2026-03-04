"""Tests for the Timer system (bucktrader.timer)."""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

import pytest

from bucktrader.dataseries import date2num
from bucktrader.timer import SESSION_END, SESSION_START, Timer, _apply_offset


# -- Constants -----------------------------------------------------------------


class TestConstants:
    """SESSION_START and SESSION_END have expected values."""

    def test_session_start(self):
        assert SESSION_START == time(0, 0, 0)

    def test_session_end(self):
        assert SESSION_END == time(23, 59, 59)


# -- Timer Creation ------------------------------------------------------------


class TestTimerCreation:
    """Timer can be created with various parameter combinations."""

    def test_defaults(self):
        timer = Timer()
        assert timer.when == SESSION_START
        assert timer.offset == timedelta(0)
        assert timer.repeat == timedelta(0)
        assert timer.weekdays == []
        assert timer.monthdays == []
        assert timer.weekcarry is True
        assert timer.monthcarry is True
        assert timer.allow is None
        assert timer.cheat is False
        assert timer.strats is False

    def test_custom_when(self):
        t = time(9, 30, 0)
        timer = Timer(when=t)
        assert timer.when == t

    def test_with_offset(self):
        timer = Timer(when=time(9, 30), offset=timedelta(minutes=5))
        assert timer.offset == timedelta(minutes=5)

    def test_with_weekdays(self):
        timer = Timer(weekdays=[1, 3, 5])
        assert timer.weekdays == [1, 3, 5]

    def test_with_monthdays(self):
        timer = Timer(monthdays=[1, 15])
        assert timer.monthdays == [1, 15]

    def test_cheat_mode(self):
        timer = Timer(cheat=True)
        assert timer.cheat is True

    def test_repr(self):
        timer = Timer(when=time(10, 0), cheat=True, weekdays=[1, 5])
        text = repr(timer)
        assert "Timer" in text
        assert "cheat=True" in text


# -- Timer.check() -------------------------------------------------------------


class TestTimerCheck:
    """Timer.check() fires at the right times."""

    def _make_dt_num(self, year, month, day, hour=0, minute=0, second=0):
        """Create a date2num float for a specific datetime."""
        dt = datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)
        return date2num(dt)

    def test_fires_at_session_start(self):
        timer = Timer(when=SESSION_START)
        dt_num = self._make_dt_num(2024, 1, 2, 0, 0, 0)
        assert timer.check(dt_num) is True

    def test_does_not_fire_twice_same_date(self):
        timer = Timer(when=SESSION_START)
        dt_num = self._make_dt_num(2024, 1, 2, 0, 0, 0)
        assert timer.check(dt_num) is True
        # Same date, same time - should not fire again.
        assert timer.check(dt_num) is False

    def test_fires_on_different_dates(self):
        timer = Timer(when=SESSION_START)
        dt1 = self._make_dt_num(2024, 1, 2, 0, 0, 0)
        dt2 = self._make_dt_num(2024, 1, 3, 0, 0, 0)
        assert timer.check(dt1) is True
        assert timer.check(dt2) is True

    def test_fires_at_specific_time(self):
        timer = Timer(when=time(10, 0, 0))
        # Before the time - should not fire.
        dt_before = self._make_dt_num(2024, 1, 2, 9, 30, 0)
        assert timer.check(dt_before) is False

        # At or after the time - should fire.
        dt_at = self._make_dt_num(2024, 1, 2, 10, 0, 0)
        assert timer.check(dt_at) is True

    def test_fires_with_offset(self):
        timer = Timer(when=time(10, 0, 0), offset=timedelta(minutes=15))
        # Effective fire time: 10:15
        dt_before = self._make_dt_num(2024, 1, 2, 10, 10, 0)
        assert timer.check(dt_before) is False

        dt_at = self._make_dt_num(2024, 1, 2, 10, 15, 0)
        assert timer.check(dt_at) is True

    def test_weekday_filter(self):
        # Only fire on Monday (1).
        timer = Timer(when=SESSION_START, weekdays=[1], weekcarry=False)
        # 2024-01-02 is a Tuesday (2).
        dt_tue = self._make_dt_num(2024, 1, 2, 0, 0, 0)
        assert timer.check(dt_tue) is False

        # 2024-01-08 is a Monday (1).
        dt_mon = self._make_dt_num(2024, 1, 8, 0, 0, 0)
        assert timer.check(dt_mon) is True

    def test_weekday_carry(self):
        # Only fire on Saturday (6), with carry.
        timer = Timer(when=SESSION_START, weekdays=[6], weekcarry=True)

        # Tuesday - not the right day, but carry pending.
        dt_tue = self._make_dt_num(2024, 1, 2, 0, 0, 0)
        assert timer.check(dt_tue) is False

        # Saturday - should fire (the carried day).
        dt_sat = self._make_dt_num(2024, 1, 6, 0, 0, 0)
        assert timer.check(dt_sat) is True

    def test_monthday_filter(self):
        # Only fire on the 15th.
        timer = Timer(when=SESSION_START, monthdays=[15], monthcarry=False)

        dt_2 = self._make_dt_num(2024, 1, 2, 0, 0, 0)
        assert timer.check(dt_2) is False

        dt_15 = self._make_dt_num(2024, 1, 15, 0, 0, 0)
        assert timer.check(dt_15) is True

    def test_allow_filter(self):
        # Custom filter that only allows even days.
        from bucktrader.dataseries import num2date

        def only_even(dt):
            return dt.day % 2 == 0

        timer = Timer(when=SESSION_START, allow=only_even)

        dt_odd = self._make_dt_num(2024, 1, 3, 0, 0, 0)
        assert timer.check(dt_odd) is False

        dt_even = self._make_dt_num(2024, 1, 4, 0, 0, 0)
        assert timer.check(dt_even) is True

    def test_repeat(self):
        timer = Timer(when=time(9, 0), repeat=timedelta(hours=1))

        # Fire at 9:00.
        dt1 = self._make_dt_num(2024, 1, 2, 9, 0, 0)
        assert timer.check(dt1) is True

        # Not enough time has passed (9:30).
        dt2 = self._make_dt_num(2024, 1, 2, 9, 30, 0)
        assert timer.check(dt2) is False

        # One hour later (10:00).
        dt3 = self._make_dt_num(2024, 1, 2, 10, 0, 0)
        assert timer.check(dt3) is True


# -- _apply_offset helper -----------------------------------------------------


class TestApplyOffset:
    """_apply_offset correctly adjusts time values."""

    def test_no_offset(self):
        result = _apply_offset(time(10, 0), timedelta(0))
        assert result == time(10, 0)

    def test_positive_offset(self):
        result = _apply_offset(time(10, 0), timedelta(minutes=30))
        assert result == time(10, 30)

    def test_negative_offset(self):
        result = _apply_offset(time(10, 0), timedelta(minutes=-30))
        assert result == time(9, 30)
