"""Commission information and calculation for the bucktrader framework.

CommInfoBase provides the interface and default logic for computing commissions,
margin requirements, position costs, and credit interest for both stock-like
and futures-like instruments.
"""

from __future__ import annotations

import math
from datetime import datetime
from enum import IntEnum
from typing import Any


class CommType(IntEnum):
    """Commission calculation mode."""

    COMM_PERC = 0  # Percentage of trade value.
    COMM_FIXED = 1  # Fixed amount per unit.


class CommInfoBase:
    """Base class for all commission schemes.

    Handles two fundamental modes:

    Stock-like (stocklike=True):
        - Full position value is deducted from cash.
        - No margin requirement.
        - P&L realized on close only.
        - Commission as percentage of value or fixed per share.

    Futures-like (margin is set):
        - Only margin is deducted from cash.
        - Positions are marked-to-market daily via cashadjust().
        - P&L flows through cash each bar.
        - Contract multiplier applies: value = size * price * mult.

    Attributes:
        commission: Commission rate (percentage or fixed per unit).
        mult: Contract multiplier (futures).
        margin: Margin requirement per contract (None = stock-like).
        commtype: COMM_PERC or COMM_FIXED.
        stocklike: True for stocks, False for futures.
        percabs: If True, commission is an absolute percentage (0.01 = 1%).
        interest: Annual interest rate for short positions.
        interest_long: Also charge interest on long positions.
        leverage: Leverage factor.
        automargin: Auto-calculate margin from price * mult.
    """

    COMM_PERC = CommType.COMM_PERC
    COMM_FIXED = CommType.COMM_FIXED

    def __init__(
        self,
        commission: float = 0.0,
        mult: float = 1.0,
        margin: float | None = None,
        commtype: CommType | None = None,
        stocklike: bool = False,
        percabs: bool = False,
        interest: float = 0.0,
        interest_long: bool = False,
        leverage: float = 1.0,
        automargin: bool = False,
    ):
        self.commission = commission
        self.mult = mult
        self.margin = margin
        self.stocklike = stocklike
        self.percabs = percabs
        self.interest = interest
        self.interest_long = interest_long
        self.leverage = leverage
        self.automargin = automargin

        # Determine commission type if not explicitly set.
        if commtype is not None:
            self.commtype = commtype
        elif stocklike:
            self.commtype = CommType.COMM_PERC
        else:
            self.commtype = CommType.COMM_FIXED

        # If margin is explicitly set, we are futures-like regardless of stocklike flag.
        if margin is not None:
            self.stocklike = False

    def _get_margin(self, price: float) -> float:
        """Return the effective margin per contract for the given price."""
        if self.automargin:
            return price * self.mult
        if self.margin is not None:
            return self.margin
        # Stock-like: full value.
        return price * self.mult

    def getsize(self, price: float, cash: float) -> int:
        """Return the maximum number of units affordable with *cash* at *price*.

        For stocks: cash / price.
        For futures: cash / margin_per_contract.
        """
        if price <= 0:
            return 0
        if self.stocklike:
            effective_price = price / self.leverage
            return int(cash // effective_price)
        else:
            margin = self._get_margin(price)
            if margin <= 0:
                return 0
            return int(cash // margin)

    def getoperationcost(self, size: float, price: float) -> float:
        """Return the cash cost to open a position of *size* at *price*.

        For stocks: abs(size) * price (divided by leverage).
        For futures: abs(size) * margin_per_contract.
        """
        if self.stocklike:
            return abs(size) * price / self.leverage
        else:
            return abs(size) * self._get_margin(price)

    def getvaluesize(self, size: float, price: float) -> float:
        """Return the market value of a position of *size* at *price*.

        Always uses the contract multiplier.
        """
        return abs(size) * price * self.mult

    def getvalue(self, position: Any, price: float) -> float:
        """Return the current value of a position at market *price*.

        Args:
            position: An object with a .size attribute.
            price: Current market price.
        """
        size = getattr(position, "size", 0)
        return self.getvaluesize(size, price)

    def getcommission(self, size: float, price: float) -> float:
        """Return the commission for a trade of *size* at *price*.

        COMM_PERC: commission * abs(size) * price * mult
            (if not percabs, commission is treated as a fraction of 100,
             i.e., divided by 100 first).
        COMM_FIXED: commission * abs(size).
        """
        if self.commtype == CommType.COMM_PERC:
            rate = self.commission if self.percabs else self.commission / 100.0
            return rate * abs(size) * price * self.mult
        else:
            return self.commission * abs(size)

    def profitandloss(
        self, size: float, price: float, newprice: float
    ) -> float:
        """Return the gross P&L for moving from *price* to *newprice*.

        P&L = size * (newprice - price) * mult
        """
        return size * (newprice - price) * self.mult

    def cashadjust(
        self, size: float, price: float, newprice: float
    ) -> float:
        """Return the cash adjustment for a futures mark-to-market move.

        For stock-like instruments this returns 0 (no daily settlement).
        For futures: size * (newprice - price) * mult.
        """
        if self.stocklike:
            return 0.0
        return size * (newprice - price) * self.mult

    def get_credit_interest(
        self,
        data: Any,
        pos: Any,
        dt: datetime | None = None,
    ) -> float:
        """Return the daily interest charge for position *pos*.

        Interest is charged on short positions (and optionally long positions).
        The annual rate is divided by 365 to get a daily charge.

        Args:
            data: The data feed (used for current price if needed).
            pos: A position-like object with .size and .price attributes.
            dt: Current datetime (unused in base implementation).

        Returns:
            A non-negative interest charge (always deducted from cash).
        """
        if self.interest == 0.0:
            return 0.0

        size = getattr(pos, "size", 0)
        if size == 0:
            return 0.0

        if size > 0 and not self.interest_long:
            return 0.0

        price = getattr(pos, "price", 0.0)
        value = abs(size) * price * self.mult
        daily_rate = self.interest / 365.0
        return value * daily_rate

    def __repr__(self) -> str:
        mode = "stock" if self.stocklike else "futures"
        return (
            f"CommInfoBase(mode={mode}, commission={self.commission}, "
            f"mult={self.mult}, margin={self.margin})"
        )
