"""Position sizing logic for the bucktrader framework.

Sizers determine order size when the user passes size=None to buy/sell.
They separate signal logic from position-sizing logic.

Built-in sizers:
    FixedSize       - Fixed number of shares/contracts.
    FixedReverser   - Fixed size, doubles on reversal.
    PercentSizer    - Percentage of available cash.
    AllInSizer      - Use all available cash.
    PercentSizerInt - Percentage of cash, truncated to integer.
    AllInSizerInt   - All cash, truncated to integer.
"""

from __future__ import annotations

import math
from typing import Any


class Sizer:
    """Base class for all position sizers.

    Subclasses must implement ``_getsizing`` to return the order size.
    The broker wires up the sizer via ``strategy.setsizer()``.

    Attributes:
        strategy: The strategy this sizer belongs to (set by the strategy).
        broker: The broker instance (set by the strategy).
    """

    # Default params -- subclasses override via class-level ``params``.
    params = ()

    def __init__(self, **kwargs: Any) -> None:
        # Build params from class-level declaration + kwargs overrides.
        self._params: dict[str, Any] = {}
        for key, default in self.__class__.params:
            self._params[key] = kwargs.pop(key, default)
        if kwargs:
            raise TypeError(
                f"Unexpected keyword arguments: {', '.join(kwargs.keys())}"
            )
        self.strategy: Any = None
        self.broker: Any = None

    @property
    def p(self) -> _ParamsAccessor:
        """Attribute-style access to sizer params."""
        return _ParamsAccessor(self._params)

    def getsizing(
        self,
        comminfo: Any,
        cash: float,
        data: Any,
        isbuy: bool,
    ) -> float:
        """Public entry point. Delegates to ``_getsizing``."""
        return self._getsizing(comminfo, cash, data, isbuy)

    def _getsizing(
        self,
        comminfo: Any,
        cash: float,
        data: Any,
        isbuy: bool,
    ) -> float:
        """Return the order size. Override in subclasses.

        Args:
            comminfo: Commission scheme for the data feed.
            cash: Available cash in the portfolio.
            data: The data feed being traded.
            isbuy: True for a buy order, False for sell.

        Returns:
            The number of shares/contracts to order.
        """
        raise NotImplementedError


class _ParamsAccessor:
    """Lightweight proxy providing attribute access to a params dict."""

    def __init__(self, params: dict[str, Any]) -> None:
        object.__setattr__(self, "_params", params)

    def __getattr__(self, name: str) -> Any:
        params = object.__getattribute__(self, "_params")
        try:
            return params[name]
        except KeyError:
            raise AttributeError(f"No parameter '{name}'")


# ---------------------------------------------------------------------------
# Built-in sizers
# ---------------------------------------------------------------------------


class FixedSize(Sizer):
    """Order a fixed number of shares/contracts.

    Params:
        stake (int): Number of units to order. Default 1.
    """

    params = (("stake", 1),)

    def _getsizing(
        self, comminfo: Any, cash: float, data: Any, isbuy: bool
    ) -> float:
        return self.p.stake


class FixedReverser(Sizer):
    """Fixed size that doubles on position reversal.

    When reversing direction (e.g., closing a long and opening a short),
    the size is doubled so the net effect is ``stake`` in the new direction.

    Params:
        stake (int): Base number of units. Default 1.
    """

    params = (("stake", 1),)

    def _getsizing(
        self, comminfo: Any, cash: float, data: Any, isbuy: bool
    ) -> float:
        position = self._get_position(data)
        pos_size = getattr(position, "size", 0) if position else 0

        # If currently flat or same direction, use stake.
        if pos_size == 0:
            return self.p.stake

        # If reversing direction, double the stake.
        if (isbuy and pos_size < 0) or (not isbuy and pos_size > 0):
            return self.p.stake * 2

        return self.p.stake

    def _get_position(self, data: Any) -> Any:
        """Retrieve current position from broker."""
        if self.broker is not None:
            return self.broker.getposition(data)
        return None


class PercentSizer(Sizer):
    """Order size as a percentage of available cash.

    Params:
        percents (float): Percentage of cash to use. Default 20.
    """

    params = (("percents", 20),)

    def _getsizing(
        self, comminfo: Any, cash: float, data: Any, isbuy: bool
    ) -> float:
        available = cash * (self.p.percents / 100.0)
        size = comminfo.getsize(self._get_price(data), available)
        return float(size)

    @staticmethod
    def _get_price(data: Any) -> float:
        """Extract the current close price from a data feed."""
        close = getattr(data, "close", None)
        if close is None:
            return 0.0
        if isinstance(close, (int, float)):
            return float(close)
        if callable(getattr(close, "__getitem__", None)):
            try:
                return float(close[0])
            except (IndexError, TypeError, KeyError):
                pass
        return 0.0


class AllInSizer(PercentSizer):
    """Use all available cash (100%).

    Params:
        percents (float): Percentage of cash. Default 100.
    """

    params = (("percents", 100),)


class PercentSizerInt(PercentSizer):
    """Percentage of cash, truncated to integer shares.

    Params:
        percents (float): Percentage of cash to use. Default 20.
    """

    def _getsizing(
        self, comminfo: Any, cash: float, data: Any, isbuy: bool
    ) -> float:
        size = super()._getsizing(comminfo, cash, data, isbuy)
        return float(int(size))


class AllInSizerInt(AllInSizer):
    """Use all available cash, truncated to integer shares.

    Params:
        percents (float): Percentage of cash. Default 100.
    """

    def _getsizing(
        self, comminfo: Any, cash: float, data: Any, isbuy: bool
    ) -> float:
        size = super()._getsizing(comminfo, cash, data, isbuy)
        return float(int(size))
