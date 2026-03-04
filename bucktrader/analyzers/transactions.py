"""Transactions analyzer.

Logs all order executions with datetime, size, price, and value.
Results keyed by datetime.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from bucktrader.analyzer import Analyzer
from bucktrader.order import OrderStatus


class Transactions(Analyzer):
    """Transaction log analyzer.

    Records each completed order execution as a list entry keyed by
    the execution datetime.

    Each entry is a list of dicts:
        [{"size": ..., "price": ..., "value": ...}, ...]

    Multiple fills on the same datetime are grouped together.
    """

    def __init__(self, strategy: Any = None) -> None:
        super().__init__(strategy)

    def notify_order(self, order: Any) -> None:
        """Record completed order executions."""
        status = getattr(order, "status", None)
        if status not in (OrderStatus.Completed, OrderStatus.Partial):
            return

        # Extract execution details from the most recent execution bit.
        bits = getattr(order, "execution_bits", [])
        if not bits:
            return

        # Only process the latest bit (avoid re-recording old bits).
        bit = bits[-1]
        dt = getattr(bit, "dt", None)
        size = getattr(bit, "size", 0.0)
        price = getattr(bit, "price", 0.0)
        value = getattr(bit, "value", 0.0)

        if dt is None:
            dt = "unknown"

        entry = {
            "size": size,
            "price": price,
            "value": value,
        }

        # Group by datetime key.
        if dt not in self.rets:
            self.rets[dt] = []

        self.rets[dt].append(entry)
