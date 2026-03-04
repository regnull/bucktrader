"""BuySell observer -- marks buy and sell signals on the price chart.

Lines:
    buy  -- price at which a buy order was executed (NaN otherwise)
    sell -- price at which a sell order was executed (NaN otherwise)
"""

from __future__ import annotations

import math
from typing import Any

from bucktrader.observer import Observer
from bucktrader.order import OrderStatus


NaN = float("nan")


class BuySell(Observer):
    """Observer that marks buy/sell execution prices on the chart."""

    _line_names = ("buy", "sell")

    def __init__(self, strategy: Any = None) -> None:
        super().__init__(strategy)
        self._completed_orders: list[Any] = []

    def notify_order(self, order: Any) -> None:
        """Track completed orders for marking on the chart."""
        if getattr(order, "status", None) == OrderStatus.Completed:
            self._completed_orders.append(order)

    def next(self) -> None:
        # Default to NaN (no signal).
        buy_price = NaN
        sell_price = NaN

        # Process any completed orders from this bar.
        for order in self._completed_orders:
            exec_price = getattr(order.executed, "price", NaN)
            if getattr(order, "is_buy", False):
                buy_price = exec_price
            else:
                sell_price = exec_price

        self.lines.buy[0] = buy_price
        self.lines.sell[0] = sell_price

        # Clear the completed orders for the next bar.
        self._completed_orders.clear()
