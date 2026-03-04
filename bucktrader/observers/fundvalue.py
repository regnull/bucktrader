"""Fund value observer."""

from __future__ import annotations

from typing import Any

from bucktrader.observer import Observer


class FundValue(Observer):
    """Observer that records broker fund value per bar."""

    _line_names = ("fundvalue",)

    def next(self) -> None:
        if self.broker is None:
            return
        self.lines.fundvalue[0] = self.broker.get_fundvalue()
