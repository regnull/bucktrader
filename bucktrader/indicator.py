"""Base Indicator class for the bucktrader framework.

An Indicator transforms input lines (price data) into output lines (computed
values).  It auto-registers with its owning strategy, tracks its minimum
period, and supports both event-driven (next) and vectorized (once)
computation.

Class hierarchy (logical):
    LineIterator -> DataAccessor -> IndicatorBase -> Indicator

In practice we build on the lightweight dataseries primitives so that
indicators can be tested without the full Cortex engine.
"""

from __future__ import annotations

import math
from typing import Any

from bucktrader.dataseries import DataSeries, LineBuffer

NaN = float("nan")

# Component type constant (matches metabase.IndType)
IndType = 0


class Indicator:
    """Base class for all technical indicators.

    Subclasses declare:
        lines  -- tuple of output line names, e.g. ("sma",)
        params -- tuple of (name, default) pairs, e.g. (("period", 20),)

    Computation is done in one of three ways:
        1. Declarative: assign line expressions in __init__
        2. Imperative: override next() to set self.lines.<name>[0]
        3. Vectorized: override once(start, end) for array processing

    Attributes:
        data:   The primary input data feed (first positional arg).
        datas:  All input data feeds.
        lines:  Container with named output LineBuffer instances.
        p:      Parameter accessor with attribute-style access.
        _minperiod: Minimum number of bars before output is valid.
        _owner: The owning strategy (if any).
    """

    # Subclass declarations (consumed by __init_subclass__)
    lines: tuple[str, ...] = ()
    params: tuple[tuple[str, Any], ...] = ()

    # Indicator type identifier
    _ltype = IndType
    _mindatas = 1
    _nextforce = False

    # Plot defaults
    plotinfo: dict[str, Any] = {"plot": True, "subplot": True}
    plotlines: dict[str, Any] = {}

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Process lines and params declarations on subclass creation."""
        super().__init_subclass__(**kwargs)

        # Collect lines from the entire MRO (parent first, child last)
        all_lines: list[str] = []
        for klass in reversed(cls.__mro__):
            declared = klass.__dict__.get("lines", ())
            if isinstance(declared, str):
                declared = (declared,)
            for name in declared:
                if name not in all_lines:
                    all_lines.append(name)
        cls._all_lines: tuple[str, ...] = tuple(all_lines)

        # Collect params from the entire MRO
        all_params: list[tuple[str, Any]] = []
        seen_params: set[str] = set()
        for klass in reversed(cls.__mro__):
            declared = klass.__dict__.get("params", ())
            for pair in declared:
                pname = pair[0]
                if pname in seen_params:
                    # Override: update in place
                    for i, (n, _) in enumerate(all_params):
                        if n == pname:
                            all_params[i] = pair
                            break
                else:
                    seen_params.add(pname)
                    all_params.append(pair)
        cls._all_params: tuple[tuple[str, Any], ...] = tuple(all_params)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        # ----- Parse data inputs -----
        self.datas: list[Any] = []
        remaining_args: list[Any] = []
        for arg in args:
            if _is_data_source(arg):
                self.datas.append(arg)
            else:
                remaining_args.append(arg)

        self.data: Any = self.datas[0] if self.datas else None

        # Convenience aliases: data0, data1, ...
        for idx, d in enumerate(self.datas):
            setattr(self, f"data{idx}", d)

        # ----- Build params -----
        param_defaults = dict(getattr(self.__class__, "_all_params", ()))
        self._params_dict: dict[str, Any] = {}
        for pname, pdefault in param_defaults.items():
            self._params_dict[pname] = kwargs.pop(pname, pdefault)
        self.p = _ParamsAccessor(self._params_dict)
        self.params = self.p

        # ----- Build output lines -----
        line_names = getattr(self.__class__, "_all_lines", ())
        self.lines = _LinesContainer(line_names)

        # Expose lines as attributes: self.lines.sma -> LineBuffer
        # Also: self.line -> first line (shortcut)
        if line_names:
            self.line = self.lines[0]

        # ----- Min period -----
        self._minperiod: int = 1

        # Inherit min period from input data
        for d in self.datas:
            dmp = getattr(d, "_minperiod", 1)
            if dmp > self._minperiod:
                self._minperiod = dmp

        # ----- Owner registration -----
        self._owner: Any = kwargs.pop("_owner", None)

        # ----- Child indicators -----
        self._indicators: list[Indicator] = []

        # ----- Lifecycle state -----
        self._prenext_count: int = 0
        self._nextstart_called: bool = False

    # ------------------------------------------------------------------
    # Period management
    # ------------------------------------------------------------------

    def addminperiod(self, minperiod: int) -> None:
        """Add to the minimum period (accounts for overlapping bar)."""
        self._minperiod += minperiod - 1

    def setminperiod(self, minperiod: int) -> None:
        """Set the minimum period to an absolute value."""
        self._minperiod = minperiod

    def updateminperiod(self, minperiod: int) -> None:
        """Update min period only if the new value is larger."""
        if minperiod > self._minperiod:
            self._minperiod = minperiod

    @property
    def minperiod(self) -> int:
        return self._minperiod

    # ------------------------------------------------------------------
    # Lifecycle hooks (override in subclass)
    # ------------------------------------------------------------------

    def prenext(self) -> None:
        """Called during warmup (bar count < minperiod)."""

    def nextstart(self) -> None:
        """Called once when bar count == minperiod."""
        self.next()

    def next(self) -> None:
        """Called for each bar after warmup. Override to compute outputs."""

    def preonce(self, start: int, end: int) -> None:
        """Vectorized warmup."""

    def oncestart(self, start: int, end: int) -> None:
        """Vectorized first valid range."""
        self.once(start, end)

    def once(self, start: int, end: int) -> None:
        """Vectorized main computation. Override for batch processing."""

    # ------------------------------------------------------------------
    # Auto-generation: once() from next()
    # ------------------------------------------------------------------

    def once_via_next(self, start: int, end: int) -> None:
        """Generate vectorized output by calling next() in a loop.

        Used when an indicator defines next() but not once().
        """
        for i in range(start, end):
            # Position all data line pointers at bar i
            for d in self.datas:
                _set_data_idx(d, i)
            # Position output line pointers
            for buf in self.lines:
                buf._idx = i
            self.next()

    # ------------------------------------------------------------------
    # Bar dispatch (called by engine or test harness)
    # ------------------------------------------------------------------

    def _onbar(self, bar_index: int) -> None:
        """Dispatch the correct lifecycle hook for the current bar.

        Args:
            bar_index: 1-based count of bars processed so far.
        """
        # Advance child indicators first
        for child in self._indicators:
            child._onbar(bar_index)

        if bar_index < self._minperiod:
            self._prenext_count += 1
            self.prenext()
        elif not self._nextstart_called:
            self._nextstart_called = True
            self.nextstart()
        else:
            self.next()

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_with_owner(self, owner: Any) -> None:
        """Register this indicator with an owner (strategy or indicator)."""
        self._owner = owner
        if hasattr(owner, "addindicator"):
            owner.addindicator(self)
        elif hasattr(owner, "_indicators"):
            owner._indicators.append(self)
        # Propagate our min period to the owner
        owner_mp = getattr(owner, "_minperiod", 1)
        if self._minperiod > owner_mp:
            owner._minperiod = self._minperiod

    # ------------------------------------------------------------------
    # Indexing: delegate to first output line
    # ------------------------------------------------------------------

    def __getitem__(self, index: int) -> float:
        """Delegate indexing to the first output line."""
        if self.lines and len(self.lines) > 0:
            return self.lines[0][index]
        raise IndexError("Indicator has no output lines")

    def __len__(self) -> int:
        if self.lines and len(self.lines) > 0:
            return len(self.lines[0])
        return 0

    def __repr__(self) -> str:
        cls_name = type(self).__name__
        line_names = getattr(self.__class__, "_all_lines", ())
        return f"<{cls_name} lines={line_names} minperiod={self._minperiod}>"


# ---------------------------------------------------------------------------
# _LinesContainer -- Holds named output LineBuffers
# ---------------------------------------------------------------------------


class _LinesContainer:
    """Container for an indicator's output lines.

    Supports both indexed and named access:
        container[0]        -> first LineBuffer
        container.sma       -> LineBuffer named 'sma'
    """

    def __init__(self, names: tuple[str, ...] = ()) -> None:
        self._names: tuple[str, ...] = names
        self._buffers: list[LineBuffer] = [
            LineBuffer(name=n) for n in names
        ]

    def __getitem__(self, index: int) -> LineBuffer:
        return self._buffers[index]

    def __setitem__(self, index: int, value: LineBuffer) -> None:
        self._buffers[index] = value

    def __getattr__(self, name: str) -> LineBuffer:
        if name.startswith("_"):
            raise AttributeError(name)
        names = object.__getattribute__(self, "_names")
        if name in names:
            idx = names.index(name)
            return object.__getattribute__(self, "_buffers")[idx]
        raise AttributeError(f"No line named '{name}'")

    def __setattr__(self, name: str, value: Any) -> None:
        if name.startswith("_"):
            object.__setattr__(self, name, value)
            return
        try:
            names = object.__getattribute__(self, "_names")
        except AttributeError:
            object.__setattr__(self, name, value)
            return
        if name in names:
            idx = names.index(name)
            buffers = object.__getattribute__(self, "_buffers")
            if isinstance(value, LineBuffer):
                buffers[idx] = value
            else:
                # Scalar assignment to current position
                buffers[idx][0] = float(value)
            return
        object.__setattr__(self, name, value)

    def __len__(self) -> int:
        return len(self._buffers)

    def __iter__(self):
        return iter(self._buffers)

    def forward(self) -> None:
        """Advance all line pointers by one."""
        for buf in self._buffers:
            buf.forward()

    def home(self) -> None:
        """Reset all line pointers to the beginning."""
        for buf in self._buffers:
            buf.home()


# ---------------------------------------------------------------------------
# _ParamsAccessor
# ---------------------------------------------------------------------------


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

    def __repr__(self) -> str:
        params = object.__getattribute__(self, "_params")
        items = ", ".join(f"{k}={v!r}" for k, v in params.items())
        return f"Params({items})"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_data_source(obj: Any) -> bool:
    """Return True if obj looks like a data source (has line-like attributes)."""
    if isinstance(obj, DataSeries):
        return True
    if isinstance(obj, LineBuffer):
        return True
    if isinstance(obj, Indicator):
        return True
    # Duck-type check
    return hasattr(obj, "close") or hasattr(obj, "_idx")


def _set_data_idx(data: Any, idx: int) -> None:
    """Position a data source's line pointers at a given absolute index."""
    if isinstance(data, DataSeries):
        for line in data._lines.values():
            line._idx = idx
    elif isinstance(data, LineBuffer):
        data._idx = idx
    elif isinstance(data, Indicator):
        for buf in data.lines:
            buf._idx = idx
