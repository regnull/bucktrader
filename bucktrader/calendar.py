"""Trading calendar support for live/timer scheduling."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any


class TradingCalendarBase:
    """Base interface for trading calendars."""

    def _nextday(self, day: date) -> date:
        raise NotImplementedError

    def schedule(self, day: date, tz: Any = None) -> tuple[datetime, datetime]:
        raise NotImplementedError


class TradingCalendar(TradingCalendarBase):
    """Simple trading calendar with holidays and early closes."""

    def __init__(
        self,
        holidays: list[str] | None = None,
        earlydays: list[tuple[str, time]] | None = None,
        open: time = time(9, 30),
        close: time = time(16, 0),
    ) -> None:
        self.holidays = {date.fromisoformat(d) for d in (holidays or [])}
        self.earlydays = {date.fromisoformat(d): t for d, t in (earlydays or [])}
        self.open = open
        self.close = close

    def _is_trading_day(self, day: date) -> bool:
        if day.weekday() >= 5:
            return False
        if day in self.holidays:
            return False
        return True

    def _nextday(self, day: date) -> date:
        nxt = day + timedelta(days=1)
        while not self._is_trading_day(nxt):
            nxt += timedelta(days=1)
        return nxt

    def schedule(self, day: date, tz: Any = None) -> tuple[datetime, datetime]:
        if not self._is_trading_day(day):
            day = self._nextday(day)
        dopen = datetime.combine(day, self.open)
        close_time = self.earlydays.get(day, self.close)
        dclose = datetime.combine(day, close_time)
        return dopen, dclose
