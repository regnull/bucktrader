"""Lines System - the foundational data model for bucktrader.

A "line" is a time-indexed array of float64 values representing any time series:
prices, indicator outputs, datetime values, boolean signals, or arbitrary numeric data.

Key insight: index 0 always refers to the current bar. Negative indices look into
the past; positive indices look into the future (when available).

Class Hierarchy:
    LineRoot (abstract base)
    +-- LineSingle (single line base)
    |   +-- LineBuffer (actual storage)
    |       +-- LineActions (buffer + registration + min period)
    |           +-- LinesOperation (binary: line OP line)
    |           +-- LineOwnOperation (unary: OP(line))
    |           +-- LineDelay (time-shifted access: line(-N))
    |           +-- LineForward (future access: line(N))
    +-- LineMultiple (container for multiple lines)
        +-- LineSeries (named lines with descriptors)
"""

from __future__ import annotations

import math
import operator
from collections import deque
from datetime import datetime, time, timezone
from typing import Any, Callable, Optional, Sequence

import numpy as np

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

NaN = float("nan")

# Stages for the two-stage system
STAGE_INIT = 1  # Construction: operations create lazy operation objects
STAGE_EXEC = 2  # Execution: comparisons return booleans directly

# DateTime epoch: days since 0001-01-01 (matching matplotlib convention)
_EPOCH = datetime(1, 1, 1, tzinfo=timezone.utc)
_SECONDS_PER_DAY = 86400.0

# Default initial capacity for unbounded arrays
_INITIAL_CAPACITY = 256


# ---------------------------------------------------------------------------
# DateTime Utilities
# ---------------------------------------------------------------------------


def date2num(dt: datetime) -> float:
    """Convert a datetime to a float (days since epoch).

    Uses a simple epoch of 0001-01-01 UTC, matching matplotlib's convention.
    The fractional part encodes the time of day.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = dt - _EPOCH
    return delta.total_seconds() / _SECONDS_PER_DAY + 1.0


def num2date(num: float) -> datetime:
    """Convert a float (days since epoch) back to a datetime (UTC)."""
    from datetime import timedelta

    total_seconds = (num - 1.0) * _SECONDS_PER_DAY
    return _EPOCH + timedelta(seconds=total_seconds)


def time2num(t: time) -> float:
    """Convert a time object to a fractional day float.

    midnight = 0.0, noon = 0.5, 23:59:59 ~ 1.0
    """
    total_seconds = t.hour * 3600 + t.minute * 60 + t.second + t.microsecond / 1e6
    return total_seconds / _SECONDS_PER_DAY


# ---------------------------------------------------------------------------
# LineRoot - Abstract Base
# ---------------------------------------------------------------------------


class LineRoot:
    """Abstract base for all line objects.

    Provides:
    - Minimum period management (how many bars before valid output)
    - Two-stage system (Stage 1: lazy ops, Stage 2: boolean comparisons)
    - Operator overloading for arithmetic, comparison, and logical ops
    """

    def __init__(self) -> None:
        self._minperiod: int = 1
        self._stage: int = STAGE_INIT

    # -- Period management --------------------------------------------------

    def setminperiod(self, minperiod: int) -> None:
        """Set the minimum period (absolute)."""
        self._minperiod = minperiod

    def updateminperiod(self, minperiod: int) -> None:
        """Update minimum period only if the new value is larger."""
        if minperiod > self._minperiod:
            self._minperiod = minperiod

    def addminperiod(self, minperiod: int) -> None:
        """Add to the current minimum period (cumulative)."""
        self._minperiod += minperiod

    def incminperiod(self, minperiod: int) -> None:
        """Increment minimum period (no -1 adjustment)."""
        self._minperiod += minperiod

    @property
    def minperiod(self) -> int:
        return self._minperiod

    # -- Stage switching ----------------------------------------------------

    def _stage1(self) -> None:
        """Switch to Stage 1 (construction): ops create operation objects."""
        self._stage = STAGE_INIT

    def _stage2(self) -> None:
        """Switch to Stage 2 (execution): comparisons return booleans."""
        self._stage = STAGE_EXEC

    # -- Lifecycle callbacks (default no-ops) --------------------------------

    def prenext(self) -> None:
        """Called when current bar < minperiod (warmup)."""

    def nextstart(self) -> None:
        """Called exactly once when bar == minperiod (first valid bar)."""
        self.next()

    def next(self) -> None:
        """Called for each subsequent bar after minperiod."""

    def preonce(self, start: int, end: int) -> None:
        """Vectorized warmup."""

    def oncestart(self, start: int, end: int) -> None:
        """Vectorized first valid range."""
        self.once(start, end)

    def once(self, start: int, end: int) -> None:
        """Vectorized main computation."""

    # -- Operator overloading -----------------------------------------------
    # In Stage 1, all operators create operation objects.
    # In Stage 2, comparison operators return booleans directly.

    def _make_op(self, other: Any, op: Callable) -> LinesOperation:
        """Create a binary operation object."""
        return LinesOperation(self, other, op)

    def _make_rop(self, other: Any, op: Callable) -> LinesOperation:
        """Create a reverse binary operation object (other OP self)."""
        return LinesOperation(other, self, op)

    def _make_own_op(self, op: Callable) -> LineOwnOperation:
        """Create a unary operation object."""
        return LineOwnOperation(self, op)

    # Arithmetic operators - always create operation objects
    def __add__(self, other: Any) -> LinesOperation:
        return self._make_op(other, operator.add)

    def __radd__(self, other: Any) -> LinesOperation:
        return self._make_rop(other, operator.add)

    def __sub__(self, other: Any) -> LinesOperation:
        return self._make_op(other, operator.sub)

    def __rsub__(self, other: Any) -> LinesOperation:
        return self._make_rop(other, operator.sub)

    def __mul__(self, other: Any) -> LinesOperation:
        return self._make_op(other, operator.mul)

    def __rmul__(self, other: Any) -> LinesOperation:
        return self._make_rop(other, operator.mul)

    def __truediv__(self, other: Any) -> LinesOperation:
        return self._make_op(other, operator.truediv)

    def __rtruediv__(self, other: Any) -> LinesOperation:
        return self._make_rop(other, operator.truediv)

    def __floordiv__(self, other: Any) -> LinesOperation:
        return self._make_op(other, operator.floordiv)

    def __rfloordiv__(self, other: Any) -> LinesOperation:
        return self._make_rop(other, operator.floordiv)

    def __mod__(self, other: Any) -> LinesOperation:
        return self._make_op(other, operator.mod)

    def __rmod__(self, other: Any) -> LinesOperation:
        return self._make_rop(other, operator.mod)

    def __pow__(self, other: Any) -> LinesOperation:
        return self._make_op(other, operator.pow)

    def __rpow__(self, other: Any) -> LinesOperation:
        return self._make_rop(other, operator.pow)

    def __neg__(self) -> LineOwnOperation:
        return self._make_own_op(operator.neg)

    def __pos__(self) -> LineOwnOperation:
        return self._make_own_op(operator.pos)

    def __abs__(self) -> LineOwnOperation:
        return self._make_own_op(operator.abs)

    # Comparison operators - stage-dependent
    def __lt__(self, other: Any) -> Any:
        if self._stage == STAGE_EXEC:
            return self[0] < _get_value(other)
        return self._make_op(other, operator.lt)

    def __le__(self, other: Any) -> Any:
        if self._stage == STAGE_EXEC:
            return self[0] <= _get_value(other)
        return self._make_op(other, operator.le)

    def __gt__(self, other: Any) -> Any:
        if self._stage == STAGE_EXEC:
            return self[0] > _get_value(other)
        return self._make_op(other, operator.gt)

    def __ge__(self, other: Any) -> Any:
        if self._stage == STAGE_EXEC:
            return self[0] >= _get_value(other)
        return self._make_op(other, operator.ge)

    def __eq__(self, other: Any) -> Any:
        if self._stage == STAGE_EXEC:
            return self[0] == _get_value(other)
        return self._make_op(other, operator.eq)

    def __ne__(self, other: Any) -> Any:
        if self._stage == STAGE_EXEC:
            return self[0] != _get_value(other)
        return self._make_op(other, operator.ne)

    # Logical operators - stage-dependent
    def __and__(self, other: Any) -> Any:
        if self._stage == STAGE_EXEC:
            return bool(self[0]) and bool(_get_value(other))
        return self._make_op(other, lambda a, b: bool(a) and bool(b))

    def __rand__(self, other: Any) -> Any:
        if self._stage == STAGE_EXEC:
            return bool(_get_value(other)) and bool(self[0])
        return self._make_rop(other, lambda a, b: bool(a) and bool(b))

    def __or__(self, other: Any) -> Any:
        if self._stage == STAGE_EXEC:
            return bool(self[0]) or bool(_get_value(other))
        return self._make_op(other, operator.or_)

    def __ror__(self, other: Any) -> Any:
        if self._stage == STAGE_EXEC:
            return bool(_get_value(other)) or bool(self[0])
        return self._make_rop(other, operator.or_)

    def __xor__(self, other: Any) -> Any:
        if self._stage == STAGE_EXEC:
            return bool(self[0]) ^ bool(_get_value(other))
        return self._make_op(other, operator.xor)

    def __rxor__(self, other: Any) -> Any:
        if self._stage == STAGE_EXEC:
            return bool(_get_value(other)) ^ bool(self[0])
        return self._make_rop(other, operator.xor)

    # Calling a line creates a delay/forward operation
    def __call__(self, ago: int) -> LineDelay | LineForward:
        """Create a delayed or forward access line.

        line(-N) creates a LineDelay: delayed[0] == line[-N]
        line(N)  creates a LineForward: forward[0] == line[N]
        """
        if ago <= 0:
            return LineDelay(self, -ago)
        return LineForward(self, ago)

    def __getitem__(self, index: int) -> float:
        """Get value at relative index. Override in subclasses."""
        raise NotImplementedError

    def __setitem__(self, index: int, value: float) -> None:
        """Set value at relative index. Override in subclasses."""
        raise NotImplementedError

    def __len__(self) -> int:
        raise NotImplementedError

    def __bool__(self) -> bool:
        return bool(self[0])


# ---------------------------------------------------------------------------
# Helper: extract scalar value from line or scalar operand
# ---------------------------------------------------------------------------


def _get_value(other: Any, index: int = 0) -> float:
    """Return the current value of a line or a scalar."""
    if isinstance(other, LineRoot):
        return other[index]
    return float(other)


def _get_array_value(other: Any, index: int = 0) -> float:
    """Return a value from the underlying array of a line, or a scalar."""
    if isinstance(other, LineBuffer):
        return other.array[index]
    if isinstance(other, LineRoot):
        return other[index]
    return float(other)


# ---------------------------------------------------------------------------
# LineSingle - Base for Single-Line Objects
# ---------------------------------------------------------------------------


class LineSingle(LineRoot):
    """Base for objects representing a single line (one time series).

    Overrides addminperiod to subtract 1, since the overlapping bar
    is already counted in the period of the data source.
    """

    def addminperiod(self, minperiod: int) -> None:
        """Add to min period, subtracting 1 for the overlapping bar."""
        self._minperiod += minperiod - 1


# ---------------------------------------------------------------------------
# LineBuffer - Core Storage
# ---------------------------------------------------------------------------


class LineBuffer(LineSingle):
    """Core storage for a single line of time-series data.

    Supports two storage modes:
    - Unbounded: growable numpy array (default)
    - QBuffer: fixed-size circular buffer for memory saving

    The idx pointer tracks the current position (index 0 for the user).
    It starts at -1 (no data) and advances with forward().
    """

    def __init__(self) -> None:
        super().__init__()
        self._idx: int = -1
        self._lencount: int = 0
        self._extension: int = 0
        self._bindings: list[LineBuffer] = []
        self._qbuffer: bool = False

        # Unbounded mode: start with a pre-allocated numpy array
        self._capacity: int = _INITIAL_CAPACITY
        self._array: np.ndarray = np.full(self._capacity, NaN, dtype=np.float64)

    # -- Properties ---------------------------------------------------------

    @property
    def idx(self) -> int:
        """Current position in the underlying array. -1 means no data."""
        return self._idx

    @property
    def lencount(self) -> int:
        """Number of bars produced so far."""
        return self._lencount

    @property
    def extension(self) -> int:
        """Number of future positions allocated."""
        return self._extension

    @property
    def array(self) -> np.ndarray | deque:
        """The underlying storage (numpy array or deque in QBuffer mode)."""
        if self._qbuffer:
            return self._qbuffer_deque
        return self._array

    @property
    def bindings(self) -> list[LineBuffer]:
        """List of bound LineBuffers that receive values on writes."""
        return self._bindings

    # -- Core operations ----------------------------------------------------

    def forward(self, value: float = NaN, size: int = 1) -> None:
        """Move pointer forward and append value(s).

        Advances idx by size, extends storage as needed, and writes value
        at each new position. Propagates to all bindings.
        """
        for _ in range(size):
            self._idx += 1
            self._lencount += 1

            if self._qbuffer:
                self._qbuffer_deque.append(value)
                # Clamp idx to not exceed buffer boundary
                if self._idx >= self._qbuffer_maxlen:
                    self._idx = self._qbuffer_maxlen - 1
            else:
                self._ensure_capacity(self._idx + 1)
                self._array[self._idx] = value

        # Propagate to bindings
        for binding in self._bindings:
            binding.forward(value=value, size=size)

    def backwards(self, size: int = 1, force: bool = False) -> None:
        """Move pointer backward, removing the last size values.

        Used for replay operations.
        """
        if self._qbuffer and not force:
            return
        self._idx -= size
        self._lencount -= size
        if self._lencount < 0:
            self._lencount = 0
        if self._idx < -1:
            self._idx = -1

    def rewind(self, size: int = 1) -> None:
        """Move pointer backward without removing values (logical only)."""
        self._idx -= size
        if self._idx < -1:
            self._idx = -1

    def advance(self, size: int = 1) -> None:
        """Move pointer forward without appending values (logical only)."""
        self._idx += size

    def extend(self, size: int = 0) -> None:
        """Allocate future positions by appending NaN values.

        These positions can be accessed with positive indices.
        """
        if size <= 0:
            return
        self._extension += size
        if self._qbuffer:
            for _ in range(size):
                self._qbuffer_deque.append(NaN)
        else:
            needed = self._idx + 1 + size
            self._ensure_capacity(needed)
            # Fill extended positions with NaN
            start = self._idx + 1
            self._array[start : start + size] = NaN

    def home(self) -> None:
        """Reset the pointer to the beginning of the data."""
        self._idx = -1

    def reset(self) -> None:
        """Clear all data and reset to initial state."""
        self._idx = -1
        self._lencount = 0
        self._extension = 0
        if self._qbuffer:
            self._qbuffer_deque.clear()
        else:
            self._capacity = _INITIAL_CAPACITY
            self._array = np.full(self._capacity, NaN, dtype=np.float64)

    def get(self, ago: int = 0, size: int = 1) -> np.ndarray:
        """Return a slice of values relative to current position.

        ago: offset from current (0 = current, -1 = previous)
        size: number of values to return
        Returns size values ending at position ago.
        """
        end_pos = self._idx + ago + 1
        start_pos = end_pos - size
        if self._qbuffer:
            result = np.array(
                [self._qbuffer_deque[i] for i in range(start_pos, end_pos)],
                dtype=np.float64,
            )
            return result
        return self._array[start_pos:end_pos].copy()

    def getzero(self, idx: int = 0, size: int = 1) -> np.ndarray:
        """Return a slice of values using absolute index.

        idx: absolute position in the array
        size: number of values to return
        """
        if self._qbuffer:
            result = np.array(
                [self._qbuffer_deque[i] for i in range(idx, idx + size)],
                dtype=np.float64,
            )
            return result
        return self._array[idx : idx + size].copy()

    def set(self, index: int, value: float) -> None:
        """Set value at relative index and propagate to bindings.

        index: offset from current (0 = current)
        """
        pos = self._idx + index
        if self._qbuffer:
            self._qbuffer_deque[pos] = value
        else:
            self._ensure_capacity(pos + 1)
            self._array[pos] = value

        # Propagate to bindings
        for binding in self._bindings:
            binding.set(index, value)

    # -- Indexing interface --------------------------------------------------

    def __getitem__(self, index: int) -> float:
        """Get value at relative index. line[0]=current, line[-1]=previous."""
        pos = self._idx + index
        if self._qbuffer:
            return float(self._qbuffer_deque[pos])
        return float(self._array[pos])

    def __setitem__(self, index: int, value: float) -> None:
        """Set value at relative index. Propagates to bindings."""
        self.set(index, value)

    def __len__(self) -> int:
        """Number of bars produced."""
        return self._lencount

    # -- Binding management -------------------------------------------------

    def addbinding(self, target: LineBuffer) -> None:
        """Add a binding: when this buffer is written, target is also updated."""
        self._bindings.append(target)

    # -- QBuffer mode -------------------------------------------------------

    def qbuffer(self, savemem: bool = True, extrasize: int = 0) -> None:
        """Switch to circular buffer (QBuffer) mode.

        savemem: if True, enable memory-saving mode
        extrasize: extra slots beyond minperiod (for replay)
        """
        if not savemem:
            return

        maxlen = self._minperiod + extrasize
        if maxlen < 1:
            maxlen = 1
        self._qbuffer_maxlen = maxlen

        # Transfer existing data to deque
        existing = []
        if self._lencount > 0:
            end = self._idx + 1
            start = max(0, end - maxlen)
            for i in range(start, end):
                existing.append(self._array[i])

        self._qbuffer = True
        self._qbuffer_deque = deque(existing, maxlen=maxlen)
        self._idx = len(self._qbuffer_deque) - 1
        # Free the numpy array
        self._array = np.array([], dtype=np.float64)

    # -- Internal helpers ---------------------------------------------------

    def _ensure_capacity(self, needed: int) -> None:
        """Grow the underlying numpy array if needed."""
        if needed <= self._capacity:
            return
        new_capacity = max(self._capacity * 2, needed)
        new_array = np.full(new_capacity, NaN, dtype=np.float64)
        new_array[: self._capacity] = self._array
        self._array = new_array
        self._capacity = new_capacity

    def __repr__(self) -> str:
        mode = "QBuffer" if self._qbuffer else "Unbounded"
        return f"<LineBuffer mode={mode} idx={self._idx} len={self._lencount}>"


# ---------------------------------------------------------------------------
# LineActions - Buffer + Auto-Registration + Min Period
# ---------------------------------------------------------------------------


class LineActions(LineBuffer):
    """LineBuffer extended with operation-creation helpers.

    This is the base class for all operation types (LinesOperation,
    LineOwnOperation, LineDelay, LineForward). It inherits storage
    from LineBuffer and operator overloading from LineRoot.
    """

    pass


# ---------------------------------------------------------------------------
# LinesOperation - Binary Operations
# ---------------------------------------------------------------------------


class LinesOperation(LineActions):
    """Represents a binary operation: line1 OP line2, or line OP scalar.

    During next(), computes: self[0] = op(a[0], b[0])
    During once(), vectorizes: dst[i] = op(srca[i], srcb[i])
    """

    def __init__(self, a: Any, b: Any, operation: Callable) -> None:
        super().__init__()
        self._a = a
        self._b = b
        self._operation = operation
        self._b_is_line = isinstance(b, LineRoot)
        self._a_is_line = isinstance(a, LineRoot)

        # Calculate min period from operands
        minperiod = 1
        if self._a_is_line:
            minperiod = max(minperiod, a.minperiod)
        if self._b_is_line:
            minperiod = max(minperiod, b.minperiod)
        self.setminperiod(minperiod)

    def next(self) -> None:
        """Compute the operation for the current bar."""
        a_val = self._a[0] if self._a_is_line else float(self._a)
        b_val = self._b[0] if self._b_is_line else float(self._b)
        self[0] = self._operation(a_val, b_val)

    def once(self, start: int, end: int) -> None:
        """Vectorized computation over a range of bars."""
        dst = self.array
        a_is_line = self._a_is_line
        b_is_line = self._b_is_line
        op = self._operation

        if a_is_line and b_is_line:
            srca = self._a.array
            srcb = self._b.array
            for i in range(start, end):
                dst[i] = op(srca[i], srcb[i])
        elif a_is_line:
            srca = self._a.array
            b_val = float(self._b)
            for i in range(start, end):
                dst[i] = op(srca[i], b_val)
        elif b_is_line:
            a_val = float(self._a)
            srcb = self._b.array
            for i in range(start, end):
                dst[i] = op(a_val, srcb[i])
        else:
            # Both scalars - unusual but handle it
            val = op(float(self._a), float(self._b))
            for i in range(start, end):
                dst[i] = val

    def __repr__(self) -> str:
        return (
            f"<LinesOperation op={self._operation.__name__} "
            f"a={self._a!r} b={self._b!r}>"
        )


# ---------------------------------------------------------------------------
# LineOwnOperation - Unary Operations
# ---------------------------------------------------------------------------


class LineOwnOperation(LineActions):
    """Represents a unary operation: OP(line).

    During next(), computes: self[0] = op(a[0])
    During once(), vectorizes: dst[i] = op(src[i])
    """

    def __init__(self, a: Any, operation: Callable) -> None:
        super().__init__()
        self._a = a
        self._operation = operation
        self._a_is_line = isinstance(a, LineRoot)

        if self._a_is_line:
            self.setminperiod(a.minperiod)

    def next(self) -> None:
        """Compute the unary operation for the current bar."""
        a_val = self._a[0] if self._a_is_line else float(self._a)
        self[0] = self._operation(a_val)

    def once(self, start: int, end: int) -> None:
        """Vectorized computation over a range."""
        dst = self.array
        op = self._operation

        if self._a_is_line:
            src = self._a.array
            for i in range(start, end):
                dst[i] = op(src[i])
        else:
            val = op(float(self._a))
            for i in range(start, end):
                dst[i] = val

    def __repr__(self) -> str:
        return (
            f"<LineOwnOperation op={self._operation.__name__} a={self._a!r}>"
        )


# ---------------------------------------------------------------------------
# LineDelay - Time-Shifted Access
# ---------------------------------------------------------------------------


class LineDelay(LineActions):
    """Access a line's value from N bars ago.

    Created by line(-N): delayed[0] == line[-N] at any point in time.
    The delay amount N is a non-negative integer.
    """

    def __init__(self, src: LineRoot, delay: int) -> None:
        super().__init__()
        self._src = src
        self._delay = delay

        # Min period increases by the delay amount
        self.setminperiod(src.minperiod + delay)

    def next(self) -> None:
        """Read the delayed value from the source line."""
        self[0] = self._src[-self._delay]

    def once(self, start: int, end: int) -> None:
        """Vectorized delayed access."""
        dst = self.array
        if isinstance(self._src, LineBuffer):
            src = self._src.array
            delay = self._delay
            for i in range(start, end):
                dst[i] = src[i - delay]
        else:
            # Fallback: not vectorizable
            pass

    def __repr__(self) -> str:
        return f"<LineDelay src={self._src!r} delay={self._delay}>"


# ---------------------------------------------------------------------------
# LineForward - Future Access
# ---------------------------------------------------------------------------


class LineForward(LineActions):
    """Access a line's future value (requires data to be preloaded).

    Created by line(N): forward[0] == line[N] at any point in time.
    """

    def __init__(self, src: LineRoot, forward: int) -> None:
        super().__init__()
        self._src = src
        self._forward = forward

        # Min period is same as source (future data must already exist)
        self.setminperiod(src.minperiod)

    def next(self) -> None:
        """Read the forward value from the source line."""
        self[0] = self._src[self._forward]

    def once(self, start: int, end: int) -> None:
        """Vectorized forward access."""
        dst = self.array
        if isinstance(self._src, LineBuffer):
            src = self._src.array
            fwd = self._forward
            for i in range(start, end):
                dst[i] = src[i + fwd]
        else:
            pass

    def __repr__(self) -> str:
        return f"<LineForward src={self._src!r} forward={self._forward}>"


# ---------------------------------------------------------------------------
# LinesCoupler - Cross-Timeframe Adapter
# ---------------------------------------------------------------------------


class LinesCoupler(LineActions):
    """Adapts lines across different timeframes.

    Stores the latest value from the source line and fills intermediate
    bars with the last known value. Only updates when the source has
    genuinely new data.
    """

    def __init__(self, src: LineRoot) -> None:
        super().__init__()
        self._src = src
        self._last_len: int = 0

    def next(self) -> None:
        """Update with latest source value, or repeat last known value."""
        src_len = len(self._src) if hasattr(self._src, "__len__") else 0
        if src_len > self._last_len:
            # Source has new data
            self._last_len = src_len
            self[0] = self._src[0]
        elif self._lencount > 0:
            # Repeat last known value
            self[0] = self[-1] if self._idx >= 0 else NaN
        else:
            self[0] = NaN

    def __repr__(self) -> str:
        return f"<LinesCoupler src={self._src!r}>"


# ---------------------------------------------------------------------------
# LineAlias - Descriptor for Named Line Access
# ---------------------------------------------------------------------------


class LineAlias:
    """Descriptor for named access to lines within a Lines container.

    Getting returns the LineBuffer at the given index.
    Setting creates a binding from the source to the target line.

    Works on both Lines containers (direct buffer access) and LineSeries
    instances (delegates to the internal _lines container).
    """

    def __init__(self, line_index: int) -> None:
        self.line_index = line_index

    def __set_name__(self, owner: type, name: str) -> None:
        self.name = name

    def _get_buffer(self, obj: Any) -> LineBuffer:
        """Resolve the target LineBuffer from the owning object."""
        if isinstance(obj, Lines):
            return obj[self.line_index]
        # For LineSeries or LineMultiple, access the internal container
        if hasattr(obj, "_lines") and isinstance(obj._lines, Lines):
            return obj._lines[self.line_index]
        return obj[self.line_index]

    def __get__(self, obj: Any, objtype: type | None = None) -> Any:
        if obj is None:
            return self
        return self._get_buffer(obj)

    def __set__(self, obj: Any, value: Any) -> None:
        target = self._get_buffer(obj)
        # If value is a LineMultiple, take its first line
        if isinstance(value, LineMultiple):
            value = value._lines[0]
        if isinstance(value, LineRoot):
            value.addbinding(target)
        else:
            # Direct scalar assignment to current position
            target[0] = float(value)


# ---------------------------------------------------------------------------
# Lines - Container for Multiple LineBuffers
# ---------------------------------------------------------------------------


class Lines:
    """Container that holds multiple LineBuffer instances.

    Dynamically subclassed for each component type via derive().
    Supports indexed access (lines[0], lines[1]) and named access
    via LineAlias descriptors (lines.close, lines.open).
    """

    _lines_names: tuple[str, ...] = ()
    _extra_lines: int = 0

    def __init__(self) -> None:
        total = len(self._lines_names) + self._extra_lines
        self._buffers: list[LineBuffer] = [LineBuffer() for _ in range(total)]

    def __getitem__(self, index: int) -> LineBuffer:
        return self._buffers[index]

    def __setitem__(self, index: int, value: LineBuffer) -> None:
        self._buffers[index] = value

    def __len__(self) -> int:
        return len(self._buffers)

    def __iter__(self):
        return iter(self._buffers)

    @classmethod
    def getlines(cls) -> tuple[str, ...]:
        """Return all line names defined on this Lines subclass."""
        return cls._lines_names

    @classmethod
    def derive(
        cls,
        name: str,
        lines: tuple[str, ...] = (),
        extralines: int = 0,
        otherbases: tuple[type, ...] = (),
    ) -> type:
        """Create a new Lines subclass with named line access.

        Args:
            name: name for the new subclass
            lines: tuple of line names
            extralines: number of anonymous extra lines
            otherbases: additional Lines bases to inherit from

        Returns:
            A new Lines subclass with LineAlias descriptors.
        """
        # Collect all line names from base classes
        all_names = list(cls._lines_names)
        for base in otherbases:
            if hasattr(base, "_lines_names"):
                for ln in base._lines_names:
                    if ln not in all_names:
                        all_names.append(ln)
        # Add new line names
        for ln in lines:
            if ln not in all_names:
                all_names.append(ln)

        all_names_tuple = tuple(all_names)

        # Build class attributes
        attrs: dict[str, Any] = {
            "_lines_names": all_names_tuple,
            "_extra_lines": extralines,
        }

        # Add LineAlias descriptors for each named line
        for i, ln in enumerate(all_names_tuple):
            attrs[ln] = LineAlias(i)

        # Build a valid base tuple avoiding MRO conflicts.
        # If cls is already an ancestor of any otherbase, skip cls.
        # Use the most-derived bases only.
        candidate_bases = [cls] + [b for b in otherbases if b is not cls]
        # Filter: remove any base that is an ancestor of another base
        final_bases = []
        for b in candidate_bases:
            is_ancestor = any(
                b is not other and issubclass(other, b)
                for other in candidate_bases
            )
            if not is_ancestor:
                final_bases.append(b)
        if not final_bases:
            final_bases = [cls]
        new_cls = type(name, tuple(final_bases), attrs)
        return new_cls

    def reset(self) -> None:
        """Reset all contained LineBuffers."""
        for buf in self._buffers:
            buf.reset()

    def forward(self, value: float = NaN, size: int = 1) -> None:
        """Forward all contained LineBuffers."""
        for buf in self._buffers:
            buf.forward(value=value, size=size)

    def rewind(self, size: int = 1) -> None:
        """Rewind all contained LineBuffers."""
        for buf in self._buffers:
            buf.rewind(size=size)

    def home(self) -> None:
        """Home all contained LineBuffers."""
        for buf in self._buffers:
            buf.home()

    def __repr__(self) -> str:
        return (
            f"<Lines names={self._lines_names} "
            f"extra={self._extra_lines} "
            f"count={len(self._buffers)}>"
        )


# ---------------------------------------------------------------------------
# LineMultiple - Base for Multi-Line Objects
# ---------------------------------------------------------------------------


class LineMultiple(LineRoot):
    """Base for objects that contain multiple lines.

    Operations on a LineMultiple are delegated to its first (default) line.
    Stage changes and minperiod updates propagate to all contained lines.
    """

    def __init__(self, lines: Lines | None = None) -> None:
        super().__init__()
        self._lines: Lines = lines if lines is not None else Lines()

    @property
    def lines(self) -> Lines:
        """The Lines container holding all LineBuffer instances."""
        return self._lines

    @property
    def line(self) -> LineBuffer:
        """Shortcut to the first (default) line."""
        if len(self._lines) > 0:
            return self._lines[0]
        raise IndexError("No lines available")

    def __getitem__(self, index: int) -> float:
        """Delegate indexing to the first line."""
        return self.line[index]

    def __setitem__(self, index: int, value: float) -> None:
        """Delegate indexing to the first line."""
        self.line[index] = value

    def __len__(self) -> int:
        """Return length of the first line."""
        if len(self._lines) > 0:
            return len(self.line)
        return 0

    # -- Stage propagation --------------------------------------------------

    def _stage1(self) -> None:
        """Propagate Stage 1 to all lines."""
        super()._stage1()
        for buf in self._lines:
            buf._stage1()

    def _stage2(self) -> None:
        """Propagate Stage 2 to all lines."""
        super()._stage2()
        for buf in self._lines:
            buf._stage2()

    # -- Period propagation -------------------------------------------------

    def setminperiod(self, minperiod: int) -> None:
        """Set min period on self and all lines."""
        super().setminperiod(minperiod)
        for buf in self._lines:
            buf.setminperiod(minperiod)

    def updateminperiod(self, minperiod: int) -> None:
        """Update min period on self and all lines."""
        super().updateminperiod(minperiod)
        for buf in self._lines:
            buf.updateminperiod(minperiod)


# ---------------------------------------------------------------------------
# AutoInfoDict - Configuration container (for plotinfo/plotlines)
# ---------------------------------------------------------------------------


class AutoInfoDict(dict):
    """A dict subclass that supports attribute-style access.

    Used for plotinfo and plotlines configuration on LineSeries.
    """

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError:
            raise AttributeError(
                f"'{type(self).__name__}' has no attribute '{name}'"
            )

    def __setattr__(self, name: str, value: Any) -> None:
        self[name] = value

    @classmethod
    def from_defaults(cls, defaults: dict | None = None) -> AutoInfoDict:
        """Create an AutoInfoDict with optional defaults."""
        info = cls()
        if defaults:
            info.update(defaults)
        return info


# ---------------------------------------------------------------------------
# Default plotinfo/plotlines
# ---------------------------------------------------------------------------

_DEFAULT_PLOTINFO = {
    "plot": True,
    "subplot": True,
    "plotname": "",
    "plotskip": False,
    "plotabove": False,
    "plotlinelabels": False,
    "plotyhlines": [],
    "plotyhlines_": [],
    "plotforce": False,
    "plotmaster": None,
    "plotylimited": True,
}

_DEFAULT_PLOTLINES = {}


# ---------------------------------------------------------------------------
# MetaLineSeries - Metaclass for LineSeries
# ---------------------------------------------------------------------------


class MetaLineSeries(type):
    """Metaclass that processes LineSeries class definitions.

    1. Reads the 'lines' class attribute (tuple of line names)
    2. Calls Lines.derive() to create a Lines container subtype
    3. Sets up LineAlias descriptors on the class for each line
    4. Processes plotinfo and plotlines as configuration
    5. Creates aliases for alternative class names
    """

    def __new__(
        mcs,
        name: str,
        bases: tuple[type, ...],
        namespace: dict[str, Any],
    ) -> type:
        # Collect line names from the class definition
        lines_decl = namespace.get("lines", ())
        if isinstance(lines_decl, str):
            lines_decl = (lines_decl,)

        # Collect lines from bases
        base_lines: list[str] = []
        for base in bases:
            if hasattr(base, "_lines_type"):
                for ln in base._lines_type.getlines():
                    if ln not in base_lines:
                        base_lines.append(ln)

        # Merge declared lines with base lines
        all_lines: list[str] = list(base_lines)
        for ln in lines_decl:
            if ln not in all_lines:
                all_lines.append(ln)

        all_lines_tuple = tuple(all_lines)

        # Create the Lines container subtype
        lines_type = Lines.derive(
            f"{name}_Lines",
            lines=all_lines_tuple,
            extralines=namespace.get("extralines", 0),
        )
        namespace["_lines_type"] = lines_type
        namespace["_lines_names"] = all_lines_tuple

        # Remove 'lines' from namespace so it does not shadow the
        # inherited 'lines' property from LineMultiple.
        namespace.pop("lines", None)
        namespace.pop("extralines", None)

        # Process plotinfo: merge base defaults with user overrides
        base_plotinfo = {}
        for base in bases:
            if hasattr(base, "_plotinfo_defaults"):
                base_plotinfo.update(base._plotinfo_defaults)
        plotinfo = dict(_DEFAULT_PLOTINFO)
        plotinfo.update(base_plotinfo)
        ns_plotinfo = namespace.get("plotinfo", {})
        if isinstance(ns_plotinfo, dict):
            plotinfo.update(ns_plotinfo)
        namespace["_plotinfo_defaults"] = plotinfo
        # Remove 'plotinfo' only if it is a plain dict declaration,
        # not a property descriptor (which LineSeries defines).
        if isinstance(namespace.get("plotinfo"), dict):
            namespace.pop("plotinfo", None)

        # Process plotlines: merge base defaults with user overrides
        base_plotlines = {}
        for base in bases:
            if hasattr(base, "_plotlines_defaults"):
                base_plotlines.update(base._plotlines_defaults)
        plotlines = dict(_DEFAULT_PLOTLINES)
        plotlines.update(base_plotlines)
        ns_plotlines = namespace.get("plotlines", {})
        if isinstance(ns_plotlines, dict):
            plotlines.update(ns_plotlines)
        namespace["_plotlines_defaults"] = plotlines
        # Remove 'plotlines' only if it is a plain dict declaration.
        if isinstance(namespace.get("plotlines"), dict):
            namespace.pop("plotlines", None)

        # Create the class
        cls = super().__new__(mcs, name, bases, namespace)

        # Set up LineAlias descriptors on the class for each line
        for i, ln in enumerate(all_lines_tuple):
            setattr(cls, ln, LineAlias(i))

        # Process aliases
        aliases = namespace.get("alias", ())
        if isinstance(aliases, str):
            aliases = (aliases,)
        cls._aliases = aliases

        return cls


# ---------------------------------------------------------------------------
# LineSeries - Named Lines with Metadata
# ---------------------------------------------------------------------------


class LineSeries(LineMultiple, metaclass=MetaLineSeries):
    """Extends LineMultiple with named line access and plot metadata.

    Subclass this to define components with named lines:

        class MyIndicator(LineSeries):
            lines = ('sma', 'signal')
            plotinfo = {'subplot': True}

    Access lines via:
        obj.lines.sma     (via Lines container)
        obj.sma           (via LineAlias descriptor on the class)

    Note: ``lines``, ``plotinfo``, and ``plotlines`` are *declarations*
    consumed by the MetaLineSeries metaclass.  They are removed from the
    class namespace so they do not shadow the ``lines`` property inherited
    from LineMultiple or the ``plotinfo``/``plotlines`` properties below.
    """

    # These are declarations read by MetaLineSeries.__new__ and then
    # removed from the namespace.  They must appear here so that the
    # base LineSeries class itself is processed correctly.
    lines = ()
    plotinfo = {}
    plotlines = {}

    def __init__(self) -> None:
        # Create the Lines container from the derived type
        lines_instance = self._lines_type()
        super().__init__(lines=lines_instance)

        # Build plotinfo and plotlines as AutoInfoDict
        self._plotinfo = AutoInfoDict.from_defaults(self._plotinfo_defaults)
        self._plotlines = AutoInfoDict.from_defaults(self._plotlines_defaults)

    # -- Named line access is provided by LineAlias descriptors set up
    #    by MetaLineSeries on the class.  No __getattr__ override needed.

    @property
    def plotinfo(self) -> AutoInfoDict:
        """Plot configuration for this series."""
        return self._plotinfo

    @property
    def plotlines(self) -> AutoInfoDict:
        """Per-line plot configuration."""
        return self._plotlines

    def __repr__(self) -> str:
        return (
            f"<{type(self).__name__} "
            f"lines={self._lines_names} "
            f"minperiod={self._minperiod}>"
        )
