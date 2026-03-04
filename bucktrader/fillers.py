"""Volume fillers for the bucktrader framework.

Fillers control how much of an order can be filled on a single bar based
on the bar's volume. When a filler returns less than the remaining order
size, the order remains partially filled and continues to the next bar.
"""

from __future__ import annotations

from typing import Any


class FixedSize:
    """Fill up to a fixed maximum number of units per bar.

    The actual fill is the minimum of:
    - The configured *size* cap.
    - The bar's volume.
    - The order's remaining size.

    Args:
        size: Maximum units to fill per bar.
    """

    def __init__(self, size: int):
        if size <= 0:
            raise ValueError("FixedSize size must be positive")
        self.size = size

    def __call__(self, order: Any, price: float, ago: int = 0) -> float:
        """Return the maximum fill size for this bar.

        Args:
            order: The order being filled (needs order.data.volume and
                   order.executed.remsize).
            price: Execution price (unused by this filler).
            ago: Bar offset (0 = current bar).

        Returns:
            Maximum fill size (always positive).
        """
        volume = _get_volume(order, ago)
        remaining = abs(order.executed.remsize)
        return min(self.size, volume, remaining)


class FixedBarPerc:
    """Fill up to a percentage of the bar's volume.

    Args:
        perc: Fraction of bar volume to allow (e.g., 0.5 = 50%).
    """

    def __init__(self, perc: float = 1.0):
        if perc <= 0.0 or perc > 1.0:
            raise ValueError("FixedBarPerc perc must be in (0.0, 1.0]")
        self.perc = perc

    def __call__(self, order: Any, price: float, ago: int = 0) -> float:
        volume = _get_volume(order, ago)
        remaining = abs(order.executed.remsize)
        available = volume * self.perc
        return min(available, remaining)


class BarPointPerc:
    """Distribute volume across the bar's price range and take a percentage
    at the execution price point.

    The idea: imagine the bar's volume spread evenly across the high-low
    range. Only the portion at the execution price point is available.

    Args:
        perc: Fraction of the price-point volume to take (e.g., 1.0 = 100%).
    """

    def __init__(self, perc: float = 1.0):
        if perc <= 0.0 or perc > 1.0:
            raise ValueError("BarPointPerc perc must be in (0.0, 1.0]")
        self.perc = perc

    def __call__(self, order: Any, price: float, ago: int = 0) -> float:
        volume = _get_volume(order, ago)
        remaining = abs(order.executed.remsize)

        high = _get_bar_field(order, "high", ago)
        low = _get_bar_field(order, "low", ago)
        price_range = high - low

        if price_range <= 0:
            # No range (e.g., doji bar): all volume at this price.
            available = volume * self.perc
        else:
            # Volume per price point, then take perc of that.
            vol_per_point = volume / price_range
            available = vol_per_point * self.perc

        return min(available, remaining)


# ── Helpers ───────────────────────────────────────────────────────────────


def _get_volume(order: Any, ago: int = 0) -> float:
    """Safely extract volume from order.data."""
    data = getattr(order, "data", None)
    if data is None:
        return 0.0
    volume = getattr(data, "volume", None)
    if volume is None:
        return 0.0
    # Support both list-like indexing and plain float.
    if callable(getattr(volume, "__getitem__", None)):
        try:
            return float(volume[ago])
        except (IndexError, TypeError):
            return 0.0
    return float(volume)


def _get_bar_field(order: Any, field: str, ago: int = 0) -> float:
    """Safely extract a bar field (open/high/low/close) from order.data."""
    data = getattr(order, "data", None)
    if data is None:
        return 0.0
    attr = getattr(data, field, None)
    if attr is None:
        return 0.0
    if callable(getattr(attr, "__getitem__", None)):
        try:
            return float(attr[ago])
        except (IndexError, TypeError):
            return 0.0
    return float(attr)
