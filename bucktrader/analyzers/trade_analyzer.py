"""TradeAnalyzer -- comprehensive trade statistics.

Tracks: total trades (open/closed), long/short, won/lost, streaks,
P&L (gross/net), trade duration, and per-side breakdowns.
"""

from __future__ import annotations

from typing import Any

from bucktrader.analyzer import Analyzer, AutoOrderedDict


class TradeAnalyzer(Analyzer):
    """Comprehensive trade statistics analyzer.

    Subscribes to ``notify_trade()`` to collect all trade events.
    On ``stop()``, computes summary statistics into ``self.rets``.
    """

    def __init__(self, strategy: Any = None) -> None:
        super().__init__(strategy)

        # Internal accumulators.
        self._trades_total: int = 0
        self._trades_open: int = 0
        self._trades_closed: int = 0

        self._long_total: int = 0
        self._long_won: int = 0
        self._long_lost: int = 0

        self._short_total: int = 0
        self._short_won: int = 0
        self._short_lost: int = 0

        self._won_total: int = 0
        self._lost_total: int = 0

        self._won_pnl: list[float] = []
        self._lost_pnl: list[float] = []

        self._streak_won_current: int = 0
        self._streak_won_longest: int = 0
        self._streak_lost_current: int = 0
        self._streak_lost_longest: int = 0

        self._gross_pnl: list[float] = []
        self._net_pnl: list[float] = []

        self._durations: list[int] = []
        self._won_durations: list[int] = []
        self._lost_durations: list[int] = []
        self._trade_side: dict[int, str] = {}

    def notify_trade(self, trade: Any) -> None:
        """Process a trade event."""
        # Only process closed trades for final stats.
        if not getattr(trade, "isclosed", False):
            if getattr(trade, "justopened", False):
                self._trades_total += 1
                self._trades_open += 1
                size = getattr(trade, "size", 0)
                if size > 0:
                    self._long_total += 1
                    self._trade_side[getattr(trade, "ref", id(trade))] = "long"
                elif size < 0:
                    self._short_total += 1
                    self._trade_side[getattr(trade, "ref", id(trade))] = "short"
            return

        # Trade just closed.
        self._trades_open -= 1
        self._trades_closed += 1
        side = self._trade_side.pop(getattr(trade, "ref", id(trade)), None)

        gross_pnl = getattr(trade, "pnl", 0.0)
        net_pnl = getattr(trade, "pnlcomm", gross_pnl)
        self._gross_pnl.append(gross_pnl)
        self._net_pnl.append(net_pnl)

        barlen = getattr(trade, "barlen", 0)
        self._durations.append(barlen)

        # Determine if the trade was long or short by checking the entry
        # price relative to the size at opening. Use pnl to determine win/loss.
        is_won = net_pnl > 0
        is_lost = net_pnl < 0

        if is_won:
            self._won_total += 1
            self._won_pnl.append(net_pnl)
            self._won_durations.append(barlen)
            if side == "long":
                self._long_won += 1
            elif side == "short":
                self._short_won += 1
            self._streak_won_current += 1
            self._streak_lost_current = 0
            if self._streak_won_current > self._streak_won_longest:
                self._streak_won_longest = self._streak_won_current
        elif is_lost:
            self._lost_total += 1
            self._lost_pnl.append(net_pnl)
            self._lost_durations.append(barlen)
            if side == "long":
                self._long_lost += 1
            elif side == "short":
                self._short_lost += 1
            self._streak_lost_current += 1
            self._streak_won_current = 0
            if self._streak_lost_current > self._streak_lost_longest:
                self._streak_lost_longest = self._streak_lost_current
        # Net pnl == 0 is neither won nor lost.

    def stop(self) -> None:
        """Compute final statistics."""
        r = self.rets

        # Total
        r.total.total = self._trades_total
        r.total.open = self._trades_open
        r.total.closed = self._trades_closed

        # Long / Short
        r.long.total = self._long_total
        r.long.won = self._long_won
        r.long.lost = self._long_lost

        r.short.total = self._short_total
        r.short.won = self._short_won
        r.short.lost = self._short_lost

        # Streak
        r.streak.won.current = self._streak_won_current
        r.streak.won.longest = self._streak_won_longest
        r.streak.lost.current = self._streak_lost_current
        r.streak.lost.longest = self._streak_lost_longest

        # PnL
        if self._gross_pnl:
            r.pnl.gross.total = sum(self._gross_pnl)
            r.pnl.gross.average = r.pnl.gross.total / len(self._gross_pnl)
        else:
            r.pnl.gross.total = 0.0
            r.pnl.gross.average = 0.0

        if self._net_pnl:
            r.pnl.net.total = sum(self._net_pnl)
            r.pnl.net.average = r.pnl.net.total / len(self._net_pnl)
        else:
            r.pnl.net.total = 0.0
            r.pnl.net.average = 0.0

        # Won
        r.won.total = self._won_total
        if self._won_pnl:
            r.won.pnl.total = sum(self._won_pnl)
            r.won.pnl.average = r.won.pnl.total / len(self._won_pnl)
            r.won.pnl.max = max(self._won_pnl)
        else:
            r.won.pnl.total = 0.0
            r.won.pnl.average = 0.0
            r.won.pnl.max = 0.0

        # Lost
        r.lost.total = self._lost_total
        if self._lost_pnl:
            r.lost.pnl.total = sum(self._lost_pnl)
            r.lost.pnl.average = r.lost.pnl.total / len(self._lost_pnl)
            r.lost.pnl.max = min(self._lost_pnl)  # Worst loss (most negative)
        else:
            r.lost.pnl.total = 0.0
            r.lost.pnl.average = 0.0
            r.lost.pnl.max = 0.0

        # Duration (len)
        if self._durations:
            r.len.total = sum(self._durations)
            r.len.average = r.len.total / len(self._durations)
            r.len.max = max(self._durations)
            r.len.min = min(self._durations)
        else:
            r.len.total = 0
            r.len.average = 0
            r.len.max = 0
            r.len.min = 0

        if self._won_durations:
            r.len.won.total = sum(self._won_durations)
            r.len.won.average = r.len.won.total / len(self._won_durations)
            r.len.won.max = max(self._won_durations)
            r.len.won.min = min(self._won_durations)
        else:
            r.len.won.total = 0
            r.len.won.average = 0
            r.len.won.max = 0
            r.len.won.min = 0

        if self._lost_durations:
            r.len.lost.total = sum(self._lost_durations)
            r.len.lost.average = r.len.lost.total / len(self._lost_durations)
            r.len.lost.max = max(self._lost_durations)
            r.len.lost.min = min(self._lost_durations)
        else:
            r.len.lost.total = 0
            r.len.lost.average = 0
            r.len.lost.max = 0
            r.len.lost.min = 0
