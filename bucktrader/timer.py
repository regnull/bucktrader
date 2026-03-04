"""Timer system for the bucktrader Cortex engine.

Timers fire callbacks at specific times during trading sessions.
They are checked twice per bar: cheat timers before broker processing,
regular timers after strategy.next().

When a timer fires, ``strategy.notify_timer(timer, when, *args, **kwargs)``
is called.
"""

from __future__ import annotations

from datetime import time, timedelta
from typing import Any, Callable, Optional, Sequence

from bucktrader.dataseries import num2date


# -- Timer Constants -----------------------------------------------------------

SESSION_START = time(0, 0, 0)
SESSION_END = time(23, 59, 59)


# -- Timer Class ---------------------------------------------------------------


class Timer:
    """A recurring timer that fires at specific times within trading sessions.

    Parameters:
        when: Time of day to fire. Use SESSION_START or SESSION_END constants,
              or a specific ``datetime.time`` value.
        offset: Duration offset from ``when`` as a ``timedelta``.
        repeat: How often to repeat within the session as a ``timedelta``.
              ``timedelta(0)`` means fire once per session.
        weekdays: List of weekday numbers (1=Monday, 7=Sunday) on which
                  the timer is allowed to fire. Empty list means all days.
        weekcarry: If True and a weekday is missed, fire on the next
                   available day.
        monthdays: List of month days on which the timer is allowed to fire.
                   Empty list means all days.
        monthcarry: If True and a month day is missed, fire on the next
                    available day.
        allow: Optional callable filter ``allow(dt) -> bool``. The timer
               only fires when this returns True.
        tzdata: Data feed to use for timezone resolution.
        cheat: If True, fire before broker processing (cheat-on-open).
        strats: If True, deliver to all strategies; otherwise only to the
                strategy that registered the timer.
        args: Positional arguments forwarded to the callback.
        kwargs: Keyword arguments forwarded to the callback.
    """

    def __init__(
        self,
        when: time = SESSION_START,
        offset: timedelta = timedelta(0),
        repeat: timedelta = timedelta(0),
        weekdays: Optional[Sequence[int]] = None,
        weekcarry: bool = True,
        monthdays: Optional[Sequence[int]] = None,
        monthcarry: bool = True,
        allow: Optional[Callable] = None,
        tzdata: Any = None,
        cheat: bool = False,
        strats: bool = False,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        self.when = when
        self.offset = offset
        self.repeat = repeat
        self.weekdays = list(weekdays) if weekdays else []
        self.weekcarry = weekcarry
        self.monthdays = list(monthdays) if monthdays else []
        self.monthcarry = monthcarry
        self.allow = allow
        self.tzdata = tzdata
        self.cheat = cheat
        self.strats = strats
        self.args = args
        self.kwargs = kwargs

        # Internal state: track the last date we fired on, to avoid
        # firing multiple times on the same bar (unless repeat is set).
        self._last_fired_date = None
        self._last_fired_time = None
        # Track carried weekday/monthday state.
        self._weekday_carry_pending = False
        self._monthday_carry_pending = False

    def check(self, dt_num: float) -> bool:
        """Determine whether this timer should fire for the given bar datetime.

        Args:
            dt_num: Current bar datetime as a float (days since epoch).

        Returns:
            True if the timer should fire, False otherwise.
        """
        dt = num2date(dt_num)
        current_date = dt.date()
        current_time = dt.time()

        # Weekday filter (isoweekday: 1=Mon, 7=Sun).
        if self.weekdays:
            iso_wd = dt.isoweekday()
            if iso_wd not in self.weekdays:
                if self.weekcarry:
                    self._weekday_carry_pending = True
                return False
            elif self._weekday_carry_pending:
                # Carry was pending and we hit an allowed weekday.
                self._weekday_carry_pending = False
                # Fall through to fire.

        # Month day filter.
        if self.monthdays:
            if dt.day not in self.monthdays:
                if self.monthcarry:
                    self._monthday_carry_pending = True
                return False
            elif self._monthday_carry_pending:
                self._monthday_carry_pending = False

        # Custom allow filter.
        if self.allow is not None:
            if not self.allow(dt):
                return False

        # Compute the effective fire time.
        fire_time = _apply_offset(self.when, self.offset)

        # Check if the current time has reached the fire time.
        if current_time < fire_time:
            return False

        # Avoid double-firing on the same date (unless repeat is active).
        if self.repeat and self.repeat > timedelta(0):
            # With repeat, fire if enough time has passed since last fire.
            if (
                self._last_fired_date == current_date
                and self._last_fired_time is not None
            ):
                elapsed = _time_diff(current_time, self._last_fired_time)
                if elapsed < self.repeat:
                    return False
        else:
            # Without repeat, fire at most once per date.
            if self._last_fired_date == current_date:
                return False

        # Timer should fire.
        self._last_fired_date = current_date
        self._last_fired_time = current_time
        return True

    def __repr__(self) -> str:
        return (
            f"Timer(when={self.when}, cheat={self.cheat}, "
            f"weekdays={self.weekdays}, monthdays={self.monthdays})"
        )


# -- Helpers -------------------------------------------------------------------


def _apply_offset(when: time, offset: timedelta) -> time:
    """Apply a timedelta offset to a time-of-day value.

    Returns the adjusted time, clamped to a single day.
    """
    from datetime import datetime as dt_cls

    base = dt_cls(2000, 1, 1, when.hour, when.minute, when.second, when.microsecond)
    adjusted = base + offset
    return adjusted.time()


def _time_diff(t1: time, t2: time) -> timedelta:
    """Return the positive difference between two time values."""
    from datetime import datetime as dt_cls

    d1 = dt_cls(2000, 1, 1, t1.hour, t1.minute, t1.second, t1.microsecond)
    d2 = dt_cls(2000, 1, 1, t2.hour, t2.minute, t2.second, t2.microsecond)
    diff = d1 - d2
    if diff < timedelta(0):
        diff = -diff
    return diff
