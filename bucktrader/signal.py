"""Signal-based trading for the bucktrader framework.

Signals allow simple strategies to be built declaratively: instead of writing
a ``next()`` method, the user registers signal indicators. A SignalStrategy
processes these signals automatically, generating buy/sell orders.

Signal types control how positive and negative indicator values map to
trading actions (enter long, enter short, close, etc.).
"""

from __future__ import annotations

from enum import IntEnum
from typing import Any


# ---------------------------------------------------------------------------
# Signal type constants
# ---------------------------------------------------------------------------

class SignalType(IntEnum):
    """Signal type constants for signal-based trading.

    Each type defines how positive and negative indicator values
    are interpreted as trading actions.
    """

    LONGSHORT = 0    # Positive=long, Negative=short
    LONG = 1         # Positive=enter long, Negative=close long
    LONG_INV = 2     # Positive=close long, Negative=enter long
    LONG_ANY = 3     # Positive=enter/maintain long, Negative=close long
    SHORT = 4        # Positive=close short, Negative=enter short
    SHORT_INV = 5    # Positive=enter short, Negative=close short
    SHORT_ANY = 6    # Positive=close short, Negative=enter/maintain short
    LONGEXIT = 7     # Positive=close long
    SHORTEXIT = 8    # Negative=close short


# Convenience aliases at module level (match backtrader's API).
SIGNAL_LONGSHORT = SignalType.LONGSHORT
SIGNAL_LONG = SignalType.LONG
SIGNAL_LONG_INV = SignalType.LONG_INV
SIGNAL_LONG_ANY = SignalType.LONG_ANY
SIGNAL_SHORT = SignalType.SHORT
SIGNAL_SHORT_INV = SignalType.SHORT_INV
SIGNAL_SHORT_ANY = SignalType.SHORT_ANY
SIGNAL_LONGEXIT = SignalType.LONGEXIT
SIGNAL_SHORTEXIT = SignalType.SHORTEXIT


class Signal:
    """A single signal registration: type + indicator instance.

    Attributes:
        signal_type: The SignalType controlling interpretation.
        indicator: An indicator instance whose ``[0]`` value is the signal.
    """

    def __init__(self, signal_type: SignalType, indicator: Any) -> None:
        self.signal_type = signal_type
        self.indicator = indicator

    def get_value(self) -> float:
        """Return the current signal value from the indicator."""
        ind = self.indicator
        if callable(getattr(ind, "__getitem__", None)):
            try:
                return float(ind[0])
            except (IndexError, TypeError, KeyError):
                return 0.0
        return 0.0


class SignalStrategy:
    """Mixin providing signal-based order generation.

    This class is designed to be used alongside Strategy (via multiple
    inheritance or by importing into strategy.py). It processes registered
    signals in ``next()`` and generates orders automatically.

    The host strategy should call ``_process_signals()`` from its ``next()``.

    Params (managed by the host strategy):
        _accumulate: Allow adding to existing positions. Default False.
        _concurrent: Allow multiple pending orders. Default False.
        _stake: Fixed order size override. Default 0 (use sizer).
    """

    def __init__(self) -> None:
        self._signals: list[Signal] = []
        self._accumulate: bool = False
        self._concurrent: bool = False
        self._stake: int = 0

    def signal_add(self, signal_type: SignalType, indicator: Any) -> None:
        """Register a signal indicator.

        Args:
            signal_type: How to interpret the indicator's values.
            indicator: An indicator instance. Its ``[0]`` value is the signal.
        """
        self._signals.append(Signal(signal_type, indicator))

    def _process_signals(self) -> None:
        """Evaluate all registered signals and generate orders.

        Iterates through signals by type, determines the desired action
        (enter long, enter short, close, do nothing), and issues orders
        through the host strategy's buy/sell/close methods.

        Must be called from the host strategy's ``next()``.
        """
        # Collect signal values by type.
        long_signal = 0.0
        short_signal = 0.0
        longexit_signal = 0.0
        shortexit_signal = 0.0

        for sig in self._signals:
            val = sig.get_value()
            stype = sig.signal_type

            if stype == SignalType.LONGSHORT:
                long_signal += val
                short_signal -= val
            elif stype == SignalType.LONG:
                if val > 0:
                    long_signal += val
                elif val < 0:
                    longexit_signal += abs(val)
            elif stype == SignalType.LONG_INV:
                if val > 0:
                    longexit_signal += val
                elif val < 0:
                    long_signal += abs(val)
            elif stype == SignalType.LONG_ANY:
                if val > 0:
                    long_signal += val
                elif val < 0:
                    longexit_signal += abs(val)
            elif stype == SignalType.SHORT:
                if val < 0:
                    short_signal += abs(val)
                elif val > 0:
                    shortexit_signal += val
            elif stype == SignalType.SHORT_INV:
                if val > 0:
                    short_signal += val
                elif val < 0:
                    shortexit_signal += abs(val)
            elif stype == SignalType.SHORT_ANY:
                if val > 0:
                    shortexit_signal += val
                elif val < 0:
                    short_signal += abs(val)
            elif stype == SignalType.LONGEXIT:
                if val > 0:
                    longexit_signal += val
            elif stype == SignalType.SHORTEXIT:
                if val < 0:
                    shortexit_signal += abs(val)

        # Determine position state.
        pos_size = self._get_signal_position_size()

        # Check concurrency: skip if there are pending orders and not concurrent.
        if not self._concurrent and self._has_pending_orders():
            return

        # Determine size for orders.
        size = self._stake if self._stake > 0 else None

        # Process exit signals first.
        if pos_size > 0 and longexit_signal > 0:
            self.close()  # type: ignore[attr-defined]
            return

        if pos_size < 0 and shortexit_signal > 0:
            self.close()  # type: ignore[attr-defined]
            return

        # Process entry signals.
        if long_signal > 0:
            if pos_size < 0:
                self.close()  # type: ignore[attr-defined]
            if pos_size <= 0 or self._accumulate:
                self.buy(size=size)  # type: ignore[attr-defined]

        elif short_signal > 0:
            if pos_size > 0:
                self.close()  # type: ignore[attr-defined]
            if pos_size >= 0 or self._accumulate:
                self.sell(size=size)  # type: ignore[attr-defined]

    def _get_signal_position_size(self) -> float:
        """Return current position size. Override in host strategy."""
        pos = getattr(self, "position", None)
        if pos is not None:
            return getattr(pos, "size", 0)
        return 0.0

    def _has_pending_orders(self) -> bool:
        """Return True if there are pending orders. Override in host strategy."""
        orders = getattr(self, "_orders", [])
        for order in orders:
            if getattr(order, "alive", False):
                return True
        return False
