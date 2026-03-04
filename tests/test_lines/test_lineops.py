"""Tests for line operations, operators, delay, and forward."""

import math
import operator

import numpy as np
import pytest

from bucktrader.lineseries import (
    STAGE_EXEC,
    STAGE_INIT,
    LineBuffer,
    LineDelay,
    LineForward,
    LineOwnOperation,
    LineRoot,
    LinesCoupler,
    LinesOperation,
    NaN,
)


# ---------------------------------------------------------------------------
# Helper: create a LineBuffer pre-loaded with values
# ---------------------------------------------------------------------------


def make_buffer(*values: float) -> LineBuffer:
    """Create a LineBuffer and forward it through the given values."""
    buf = LineBuffer()
    for v in values:
        buf.forward(value=v)
    return buf


# ---------------------------------------------------------------------------
# LinesOperation (Binary)
# ---------------------------------------------------------------------------


class TestLinesOperation:
    """Binary operations: line OP line, line OP scalar."""

    def test_add_two_lines(self):
        a = make_buffer(1.0, 2.0, 3.0)
        b = make_buffer(10.0, 20.0, 30.0)
        op = LinesOperation(a, b, operator.add)
        op.forward()
        op.forward()
        op.forward()
        # Compute next for each bar
        a.home()
        b.home()
        op.home()
        for _ in range(3):
            a.advance()
            b.advance()
            op.advance()
            op.next()

        assert op[0] == 33.0
        assert op[-1] == 22.0
        assert op[-2] == 11.0

    def test_add_line_and_scalar(self):
        a = make_buffer(1.0, 2.0, 3.0)
        op = LinesOperation(a, 10.0, operator.add)
        op.forward()
        op.forward()
        op.forward()
        a.home()
        op.home()
        for _ in range(3):
            a.advance()
            op.advance()
            op.next()

        assert op[0] == 13.0
        assert op[-1] == 12.0
        assert op[-2] == 11.0

    def test_sub_operation(self):
        a = make_buffer(10.0, 20.0, 30.0)
        b = make_buffer(1.0, 2.0, 3.0)
        op = LinesOperation(a, b, operator.sub)
        op.forward()
        op.forward()
        op.forward()
        a.home()
        b.home()
        op.home()
        for _ in range(3):
            a.advance()
            b.advance()
            op.advance()
            op.next()

        assert op[0] == 27.0
        assert op[-1] == 18.0
        assert op[-2] == 9.0

    def test_mul_operation(self):
        a = make_buffer(2.0, 3.0, 4.0)
        b = make_buffer(5.0, 6.0, 7.0)
        op = LinesOperation(a, b, operator.mul)
        op.forward()
        op.forward()
        op.forward()
        a.home()
        b.home()
        op.home()
        for _ in range(3):
            a.advance()
            b.advance()
            op.advance()
            op.next()

        assert op[0] == 28.0
        assert op[-1] == 18.0
        assert op[-2] == 10.0

    def test_truediv_operation(self):
        a = make_buffer(10.0, 20.0, 30.0)
        op = LinesOperation(a, 2.0, operator.truediv)
        op.forward()
        op.forward()
        op.forward()
        a.home()
        op.home()
        for _ in range(3):
            a.advance()
            op.advance()
            op.next()

        assert op[0] == 15.0
        assert op[-1] == 10.0
        assert op[-2] == 5.0

    def test_minperiod_from_operands(self):
        a = LineBuffer()
        a.setminperiod(5)
        b = LineBuffer()
        b.setminperiod(10)
        op = LinesOperation(a, b, operator.add)
        assert op.minperiod == 10

    def test_minperiod_line_and_scalar(self):
        a = LineBuffer()
        a.setminperiod(7)
        op = LinesOperation(a, 3.0, operator.add)
        assert op.minperiod == 7

    def test_once_vectorized(self):
        """Test the once() vectorized computation."""
        a = make_buffer(1.0, 2.0, 3.0, 4.0, 5.0)
        b = make_buffer(10.0, 20.0, 30.0, 40.0, 50.0)
        op = LinesOperation(a, b, operator.add)
        # Allocate space in the operation's buffer
        for _ in range(5):
            op.forward()

        op.once(0, 5)
        # Check values were computed
        assert op.array[0] == 11.0
        assert op.array[1] == 22.0
        assert op.array[4] == 55.0

    def test_once_line_scalar(self):
        a = make_buffer(1.0, 2.0, 3.0)
        op = LinesOperation(a, 100.0, operator.add)
        for _ in range(3):
            op.forward()
        op.once(0, 3)
        assert op.array[0] == 101.0
        assert op.array[2] == 103.0

    def test_once_scalar_line(self):
        """Scalar OP line (reversed)."""
        b = make_buffer(1.0, 2.0, 3.0)
        op = LinesOperation(100.0, b, operator.sub)
        for _ in range(3):
            op.forward()
        op.once(0, 3)
        assert op.array[0] == 99.0
        assert op.array[2] == 97.0


# ---------------------------------------------------------------------------
# LineOwnOperation (Unary)
# ---------------------------------------------------------------------------


class TestLineOwnOperation:
    """Unary operations: OP(line)."""

    def test_neg(self):
        a = make_buffer(1.0, -2.0, 3.0)
        op = LineOwnOperation(a, operator.neg)
        op.forward()
        op.forward()
        op.forward()
        a.home()
        op.home()
        for _ in range(3):
            a.advance()
            op.advance()
            op.next()

        assert op[0] == -3.0
        assert op[-1] == 2.0
        assert op[-2] == -1.0

    def test_abs(self):
        a = make_buffer(-5.0, 3.0, -7.0)
        op = LineOwnOperation(a, operator.abs)
        op.forward()
        op.forward()
        op.forward()
        a.home()
        op.home()
        for _ in range(3):
            a.advance()
            op.advance()
            op.next()

        assert op[0] == 7.0
        assert op[-1] == 3.0
        assert op[-2] == 5.0

    def test_once_vectorized(self):
        a = make_buffer(-1.0, -2.0, -3.0)
        op = LineOwnOperation(a, operator.neg)
        for _ in range(3):
            op.forward()
        op.once(0, 3)
        assert op.array[0] == 1.0
        assert op.array[1] == 2.0
        assert op.array[2] == 3.0

    def test_minperiod_from_source(self):
        a = LineBuffer()
        a.setminperiod(5)
        op = LineOwnOperation(a, operator.neg)
        assert op.minperiod == 5


# ---------------------------------------------------------------------------
# Operator Overloading on LineRoot / LineBuffer
# ---------------------------------------------------------------------------


class TestOperatorOverloading:
    """Test that operators on LineBuffer create operation objects in Stage 1."""

    def test_add_creates_operation(self):
        a = LineBuffer()
        b = LineBuffer()
        result = a + b
        assert isinstance(result, LinesOperation)

    def test_sub_creates_operation(self):
        a = LineBuffer()
        result = a - 5.0
        assert isinstance(result, LinesOperation)

    def test_mul_creates_operation(self):
        a = LineBuffer()
        b = LineBuffer()
        result = a * b
        assert isinstance(result, LinesOperation)

    def test_truediv_creates_operation(self):
        a = LineBuffer()
        result = a / 2.0
        assert isinstance(result, LinesOperation)

    def test_floordiv_creates_operation(self):
        a = LineBuffer()
        result = a // 3.0
        assert isinstance(result, LinesOperation)

    def test_mod_creates_operation(self):
        a = LineBuffer()
        result = a % 2.0
        assert isinstance(result, LinesOperation)

    def test_pow_creates_operation(self):
        a = LineBuffer()
        result = a**2.0
        assert isinstance(result, LinesOperation)

    def test_neg_creates_own_operation(self):
        a = LineBuffer()
        result = -a
        assert isinstance(result, LineOwnOperation)

    def test_pos_creates_own_operation(self):
        a = LineBuffer()
        result = +a
        assert isinstance(result, LineOwnOperation)

    def test_abs_creates_own_operation(self):
        a = LineBuffer()
        result = abs(a)
        assert isinstance(result, LineOwnOperation)

    def test_radd_scalar_plus_line(self):
        a = LineBuffer()
        result = 5.0 + a
        assert isinstance(result, LinesOperation)

    def test_rsub_scalar_minus_line(self):
        a = LineBuffer()
        result = 5.0 - a
        assert isinstance(result, LinesOperation)

    def test_rmul_scalar_times_line(self):
        a = LineBuffer()
        result = 5.0 * a
        assert isinstance(result, LinesOperation)


class TestStage1Comparisons:
    """In Stage 1 (default), comparisons create operation objects."""

    def test_lt_creates_operation(self):
        a = LineBuffer()
        b = LineBuffer()
        result = a < b
        assert isinstance(result, LinesOperation)

    def test_le_creates_operation(self):
        a = LineBuffer()
        result = a <= 5.0
        assert isinstance(result, LinesOperation)

    def test_gt_creates_operation(self):
        a = LineBuffer()
        b = LineBuffer()
        result = a > b
        assert isinstance(result, LinesOperation)

    def test_ge_creates_operation(self):
        a = LineBuffer()
        result = a >= 0.0
        assert isinstance(result, LinesOperation)

    def test_eq_creates_operation(self):
        a = LineBuffer()
        result = a == 0.0
        assert isinstance(result, LinesOperation)

    def test_ne_creates_operation(self):
        a = LineBuffer()
        result = a != 0.0
        assert isinstance(result, LinesOperation)

    def test_and_creates_operation(self):
        a = LineBuffer()
        b = LineBuffer()
        result = a & b
        assert isinstance(result, LinesOperation)

    def test_or_creates_operation(self):
        a = LineBuffer()
        b = LineBuffer()
        result = a | b
        assert isinstance(result, LinesOperation)

    def test_xor_creates_operation(self):
        a = LineBuffer()
        b = LineBuffer()
        result = a ^ b
        assert isinstance(result, LinesOperation)


class TestStage2Comparisons:
    """In Stage 2 (execution), comparisons return booleans."""

    def test_lt_returns_bool(self):
        a = make_buffer(5.0)
        b = make_buffer(10.0)
        a._stage2()
        assert (a < b) is True

    def test_lt_false(self):
        a = make_buffer(10.0)
        b = make_buffer(5.0)
        a._stage2()
        assert (a < b) is False

    def test_gt_returns_bool(self):
        a = make_buffer(10.0)
        b = make_buffer(5.0)
        a._stage2()
        assert (a > b) is True

    def test_le_returns_bool(self):
        a = make_buffer(5.0)
        a._stage2()
        assert (a <= 5.0) is True

    def test_ge_returns_bool(self):
        a = make_buffer(5.0)
        a._stage2()
        assert (a >= 5.0) is True

    def test_eq_returns_bool(self):
        a = make_buffer(5.0)
        a._stage2()
        assert (a == 5.0) is True

    def test_ne_returns_bool(self):
        a = make_buffer(5.0)
        a._stage2()
        assert (a != 3.0) is True

    def test_and_returns_bool(self):
        a = make_buffer(1.0)
        b = make_buffer(1.0)
        a._stage2()
        assert (a & b) is True

    def test_and_false(self):
        a = make_buffer(1.0)
        b = make_buffer(0.0)
        a._stage2()
        assert (a & b) is False

    def test_or_returns_bool(self):
        a = make_buffer(0.0)
        b = make_buffer(1.0)
        a._stage2()
        assert (a | b) is True

    def test_xor_returns_bool(self):
        a = make_buffer(1.0)
        b = make_buffer(0.0)
        a._stage2()
        assert (a ^ b) is True

    def test_stage_switch_back_to_stage1(self):
        a = make_buffer(5.0)
        a._stage2()
        assert (a > 3.0) is True
        # Switch back to stage 1
        a._stage1()
        result = a > 3.0
        assert isinstance(result, LinesOperation)


# ---------------------------------------------------------------------------
# LineDelay
# ---------------------------------------------------------------------------


class TestLineDelay:
    """LineDelay: delayed[0] == source[-N]."""

    def test_create_via_call(self):
        """line(-N) creates a LineDelay."""
        a = make_buffer(1.0, 2.0, 3.0)
        delayed = a(-1)
        assert isinstance(delayed, LineDelay)

    def test_delay_value(self):
        a = make_buffer(10.0, 20.0, 30.0, 40.0, 50.0)
        delayed = LineDelay(a, delay=2)
        # Allocate space and compute
        for _ in range(5):
            delayed.forward()
        a.home()
        delayed.home()
        for _ in range(5):
            a.advance()
            delayed.advance()
            delayed.next()

        # delayed[0] should be a[-2] = 30.0 (when a is at idx=4)
        assert delayed[0] == 30.0

    def test_delay_minperiod(self):
        a = LineBuffer()
        a.setminperiod(3)
        delayed = LineDelay(a, delay=2)
        assert delayed.minperiod == 5  # 3 + 2

    def test_delay_once(self):
        a = make_buffer(1.0, 2.0, 3.0, 4.0, 5.0)
        delayed = LineDelay(a, delay=2)
        for _ in range(5):
            delayed.forward()
        delayed.once(2, 5)
        assert delayed.array[2] == 1.0
        assert delayed.array[3] == 2.0
        assert delayed.array[4] == 3.0

    def test_delay_zero(self):
        """Delay of 0 just copies current value."""
        a = make_buffer(10.0, 20.0, 30.0)
        delayed = LineDelay(a, delay=0)
        for _ in range(3):
            delayed.forward()
        a.home()
        delayed.home()
        for _ in range(3):
            a.advance()
            delayed.advance()
            delayed.next()

        assert delayed[0] == 30.0
        assert delayed[-1] == 20.0


# ---------------------------------------------------------------------------
# LineForward
# ---------------------------------------------------------------------------


class TestLineForward:
    """LineForward: forward[0] == source[N]."""

    def test_create_via_call(self):
        """line(N) with N > 0 creates a LineForward."""
        a = make_buffer(1.0, 2.0, 3.0)
        fwd = a(2)
        assert isinstance(fwd, LineForward)

    def test_forward_value(self):
        a = make_buffer(10.0, 20.0, 30.0, 40.0, 50.0)
        fwd = LineForward(a, forward=2)
        for _ in range(5):
            fwd.forward()
        a.home()
        fwd.home()
        # Process first 3 bars (where forward access is valid)
        for _ in range(3):
            a.advance()
            fwd.advance()
            fwd.next()

        # At bar 2 (idx=2), forward[0] = a[2] = a.array[4] = 50.0
        assert fwd[0] == 50.0

    def test_forward_minperiod(self):
        a = LineBuffer()
        a.setminperiod(3)
        fwd = LineForward(a, forward=2)
        assert fwd.minperiod == 3  # Same as source

    def test_forward_once(self):
        a = make_buffer(1.0, 2.0, 3.0, 4.0, 5.0)
        fwd = LineForward(a, forward=2)
        for _ in range(5):
            fwd.forward()
        fwd.once(0, 3)
        assert fwd.array[0] == 3.0
        assert fwd.array[1] == 4.0
        assert fwd.array[2] == 5.0


# ---------------------------------------------------------------------------
# LinesCoupler
# ---------------------------------------------------------------------------


class TestLinesCoupler:
    """LinesCoupler: adapt lines across timeframes."""

    def test_coupler_updates_on_new_data(self):
        src = make_buffer(100.0)
        coupler = LinesCoupler(src)
        coupler.forward()
        coupler.next()
        assert coupler[0] == 100.0

    def test_coupler_repeats_last_value(self):
        src = make_buffer(100.0)
        coupler = LinesCoupler(src)

        # First bar: new data
        coupler.forward()
        coupler.next()
        assert coupler[0] == 100.0

        # Second bar: no new source data
        coupler.forward()
        coupler.next()
        assert coupler[0] == 100.0

    def test_coupler_updates_when_source_grows(self):
        src = make_buffer(100.0)
        coupler = LinesCoupler(src)

        coupler.forward()
        coupler.next()
        assert coupler[0] == 100.0

        # Source gets new data
        src.forward(value=200.0)
        coupler.forward()
        coupler.next()
        assert coupler[0] == 200.0


# ---------------------------------------------------------------------------
# DateTime Utilities
# ---------------------------------------------------------------------------


class TestDateTimeUtilities:
    """date2num, num2date, time2num conversions."""

    def test_date2num_roundtrip(self):
        from datetime import datetime, timezone

        from bucktrader.lineseries import date2num, num2date

        dt = datetime(2024, 6, 15, 12, 30, 0, tzinfo=timezone.utc)
        num = date2num(dt)
        result = num2date(num)
        assert result.year == 2024
        assert result.month == 6
        assert result.day == 15
        assert result.hour == 12
        assert result.minute == 30

    def test_date2num_is_float(self):
        from datetime import datetime, timezone

        from bucktrader.lineseries import date2num

        dt = datetime(2024, 1, 1, tzinfo=timezone.utc)
        num = date2num(dt)
        assert isinstance(num, float)

    def test_time2num_midnight(self):
        from datetime import time

        from bucktrader.lineseries import time2num

        t = time(0, 0, 0)
        assert time2num(t) == 0.0

    def test_time2num_noon(self):
        from datetime import time

        from bucktrader.lineseries import time2num

        t = time(12, 0, 0)
        assert time2num(t) == 0.5

    def test_time2num_end_of_day(self):
        from datetime import time

        from bucktrader.lineseries import time2num

        t = time(23, 59, 59)
        result = time2num(t)
        assert result > 0.99
        assert result < 1.0

    def test_date2num_naive_datetime(self):
        """Naive datetime (no tzinfo) should still work."""
        from datetime import datetime

        from bucktrader.lineseries import date2num, num2date

        dt = datetime(2024, 3, 15, 8, 0, 0)
        num = date2num(dt)
        result = num2date(num)
        assert result.year == 2024
        assert result.month == 3
        assert result.day == 15
