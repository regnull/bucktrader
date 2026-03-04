"""Tests for LineBuffer - core storage of the Lines System."""

import math

import numpy as np
import pytest

from bucktrader.lineseries import LineBuffer, NaN


class TestLineBufferInit:
    """LineBuffer initial state."""

    def test_initial_idx_is_minus_one(self):
        buf = LineBuffer()
        assert buf.idx == -1

    def test_initial_lencount_is_zero(self):
        buf = LineBuffer()
        assert buf.lencount == 0

    def test_initial_extension_is_zero(self):
        buf = LineBuffer()
        assert buf.extension == 0

    def test_initial_bindings_empty(self):
        buf = LineBuffer()
        assert buf.bindings == []

    def test_initial_len_is_zero(self):
        buf = LineBuffer()
        assert len(buf) == 0

    def test_initial_minperiod_is_one(self):
        buf = LineBuffer()
        assert buf.minperiod == 1


class TestLineBufferForward:
    """LineBuffer.forward() - advance pointer and append values."""

    def test_forward_increments_idx(self):
        buf = LineBuffer()
        buf.forward(value=1.0)
        assert buf.idx == 0

    def test_forward_increments_lencount(self):
        buf = LineBuffer()
        buf.forward(value=1.0)
        assert buf.lencount == 1
        assert len(buf) == 1

    def test_forward_stores_value(self):
        buf = LineBuffer()
        buf.forward(value=42.0)
        assert buf[0] == 42.0

    def test_forward_default_value_is_nan(self):
        buf = LineBuffer()
        buf.forward()
        assert math.isnan(buf[0])

    def test_forward_multiple_values(self):
        buf = LineBuffer()
        buf.forward(value=10.0)
        buf.forward(value=20.0)
        buf.forward(value=30.0)
        assert buf.idx == 2
        assert buf.lencount == 3
        assert buf[0] == 30.0
        assert buf[-1] == 20.0
        assert buf[-2] == 10.0

    def test_forward_with_size(self):
        buf = LineBuffer()
        buf.forward(value=5.0, size=3)
        assert buf.idx == 2
        assert buf.lencount == 3

    def test_forward_grows_array_beyond_initial_capacity(self):
        buf = LineBuffer()
        for i in range(500):
            buf.forward(value=float(i))
        assert buf.lencount == 500
        assert buf[0] == 499.0
        assert buf[-499] == 0.0


class TestLineBufferIndexing:
    """LineBuffer indexing: line[0] = current, line[-1] = previous."""

    def test_index_zero_is_current(self):
        buf = LineBuffer()
        buf.forward(value=1.0)
        buf.forward(value=2.0)
        buf.forward(value=3.0)
        assert buf[0] == 3.0

    def test_negative_index_is_past(self):
        buf = LineBuffer()
        buf.forward(value=1.0)
        buf.forward(value=2.0)
        buf.forward(value=3.0)
        assert buf[-1] == 2.0
        assert buf[-2] == 1.0

    def test_setitem_at_current(self):
        buf = LineBuffer()
        buf.forward(value=1.0)
        buf[0] = 99.0
        assert buf[0] == 99.0

    def test_setitem_at_past(self):
        buf = LineBuffer()
        buf.forward(value=1.0)
        buf.forward(value=2.0)
        buf[-1] = 55.0
        assert buf[-1] == 55.0

    def test_positive_index_future(self):
        """Positive index accesses future positions (requires extend)."""
        buf = LineBuffer()
        buf.forward(value=1.0)
        buf.extend(size=2)
        # Future positions should be NaN initially
        assert math.isnan(buf[1])


class TestLineBufferSet:
    """LineBuffer.set() - explicit set with binding propagation."""

    def test_set_at_current(self):
        buf = LineBuffer()
        buf.forward(value=1.0)
        buf.set(0, 42.0)
        assert buf[0] == 42.0

    def test_set_propagates_to_bindings(self):
        src = LineBuffer()
        target = LineBuffer()
        src.addbinding(target)

        src.forward(value=0.0)
        target.forward(value=0.0)

        src.set(0, 99.0)
        assert target[0] == 99.0


class TestLineBufferGet:
    """LineBuffer.get() and getzero() - slice access."""

    def test_get_single_current(self):
        buf = LineBuffer()
        buf.forward(value=10.0)
        buf.forward(value=20.0)
        buf.forward(value=30.0)
        result = buf.get(ago=0, size=1)
        assert len(result) == 1
        assert result[0] == 30.0

    def test_get_slice_from_current(self):
        buf = LineBuffer()
        for v in [10.0, 20.0, 30.0, 40.0, 50.0]:
            buf.forward(value=v)
        result = buf.get(ago=0, size=3)
        np.testing.assert_array_equal(result, [30.0, 40.0, 50.0])

    def test_get_slice_from_past(self):
        buf = LineBuffer()
        for v in [10.0, 20.0, 30.0, 40.0, 50.0]:
            buf.forward(value=v)
        result = buf.get(ago=-1, size=2)
        np.testing.assert_array_equal(result, [30.0, 40.0])

    def test_getzero_absolute_index(self):
        buf = LineBuffer()
        for v in [10.0, 20.0, 30.0]:
            buf.forward(value=v)
        result = buf.getzero(idx=0, size=3)
        np.testing.assert_array_equal(result, [10.0, 20.0, 30.0])

    def test_getzero_partial(self):
        buf = LineBuffer()
        for v in [10.0, 20.0, 30.0]:
            buf.forward(value=v)
        result = buf.getzero(idx=1, size=2)
        np.testing.assert_array_equal(result, [20.0, 30.0])


class TestLineBufferBackwards:
    """LineBuffer.backwards() - remove last values."""

    def test_backwards_reduces_idx(self):
        buf = LineBuffer()
        buf.forward(value=1.0)
        buf.forward(value=2.0)
        buf.forward(value=3.0)
        buf.backwards(size=1)
        assert buf.idx == 1
        assert buf.lencount == 2

    def test_backwards_multiple(self):
        buf = LineBuffer()
        for i in range(5):
            buf.forward(value=float(i))
        buf.backwards(size=3)
        assert buf.idx == 1
        assert buf.lencount == 2

    def test_backwards_clamps_at_minus_one(self):
        buf = LineBuffer()
        buf.forward(value=1.0)
        buf.backwards(size=5)
        assert buf.idx == -1
        assert buf.lencount == 0


class TestLineBufferRewindAdvance:
    """LineBuffer.rewind() and advance() - logical pointer movement."""

    def test_rewind_moves_pointer_back(self):
        buf = LineBuffer()
        buf.forward(value=1.0)
        buf.forward(value=2.0)
        buf.forward(value=3.0)
        buf.rewind(size=2)
        assert buf.idx == 0
        # Data still there
        assert buf[0] == 1.0

    def test_advance_moves_pointer_forward(self):
        buf = LineBuffer()
        buf.forward(value=1.0)
        buf.forward(value=2.0)
        buf.forward(value=3.0)
        buf.rewind(size=2)
        buf.advance(size=2)
        assert buf.idx == 2
        assert buf[0] == 3.0


class TestLineBufferExtend:
    """LineBuffer.extend() - allocate future positions."""

    def test_extend_increases_extension_count(self):
        buf = LineBuffer()
        buf.forward(value=1.0)
        buf.extend(size=3)
        assert buf.extension == 3

    def test_extend_future_positions_are_nan(self):
        buf = LineBuffer()
        buf.forward(value=1.0)
        buf.extend(size=2)
        assert math.isnan(buf[1])
        assert math.isnan(buf[2])

    def test_extend_zero_is_noop(self):
        buf = LineBuffer()
        buf.forward(value=1.0)
        buf.extend(size=0)
        assert buf.extension == 0


class TestLineBufferHomeReset:
    """LineBuffer.home() and reset()."""

    def test_home_resets_pointer(self):
        buf = LineBuffer()
        for i in range(10):
            buf.forward(value=float(i))
        buf.home()
        assert buf.idx == -1

    def test_reset_clears_everything(self):
        buf = LineBuffer()
        for i in range(10):
            buf.forward(value=float(i))
        buf.reset()
        assert buf.idx == -1
        assert buf.lencount == 0
        assert buf.extension == 0


class TestLineBufferBindings:
    """LineBuffer bindings - writing to source propagates to targets."""

    def test_addbinding(self):
        src = LineBuffer()
        target = LineBuffer()
        src.addbinding(target)
        assert target in src.bindings

    def test_forward_propagates_to_binding(self):
        src = LineBuffer()
        target = LineBuffer()
        src.addbinding(target)
        src.forward(value=42.0)
        assert target[0] == 42.0
        assert target.lencount == 1

    def test_set_propagates_to_binding(self):
        src = LineBuffer()
        target = LineBuffer()
        src.addbinding(target)

        src.forward(value=0.0)
        # Target was also forwarded via binding
        src.set(0, 99.0)
        assert target[0] == 99.0

    def test_multiple_bindings(self):
        src = LineBuffer()
        t1 = LineBuffer()
        t2 = LineBuffer()
        src.addbinding(t1)
        src.addbinding(t2)

        src.forward(value=7.0)
        assert t1[0] == 7.0
        assert t2[0] == 7.0

    def test_chained_bindings(self):
        """A -> B -> C: writing to A propagates through B to C."""
        a = LineBuffer()
        b = LineBuffer()
        c = LineBuffer()
        a.addbinding(b)
        b.addbinding(c)

        a.forward(value=123.0)
        assert b[0] == 123.0
        assert c[0] == 123.0


class TestLineBufferQBuffer:
    """QBuffer mode - circular buffer for memory saving."""

    def test_qbuffer_switch(self):
        buf = LineBuffer()
        buf.setminperiod(3)
        buf.qbuffer(savemem=True, extrasize=0)
        # Should be in QBuffer mode now
        assert buf._qbuffer is True

    def test_qbuffer_false_is_noop(self):
        buf = LineBuffer()
        buf.qbuffer(savemem=False)
        assert buf._qbuffer is False

    def test_qbuffer_stores_values(self):
        buf = LineBuffer()
        buf.setminperiod(3)
        buf.qbuffer(savemem=True, extrasize=0)
        buf.forward(value=1.0)
        buf.forward(value=2.0)
        buf.forward(value=3.0)
        assert buf[0] == 3.0
        assert buf[-1] == 2.0
        assert buf[-2] == 1.0

    def test_qbuffer_discards_old_values(self):
        buf = LineBuffer()
        buf.setminperiod(3)
        buf.qbuffer(savemem=True, extrasize=0)
        # maxlen = 3, so only last 3 are kept
        for v in [1.0, 2.0, 3.0, 4.0, 5.0]:
            buf.forward(value=v)
        assert buf[0] == 5.0
        assert buf[-1] == 4.0
        assert buf[-2] == 3.0

    def test_qbuffer_with_extrasize(self):
        buf = LineBuffer()
        buf.setminperiod(2)
        buf.qbuffer(savemem=True, extrasize=3)
        # maxlen = 2 + 3 = 5
        for v in range(10):
            buf.forward(value=float(v))
        # Last 5 values: 5, 6, 7, 8, 9
        assert buf[0] == 9.0
        assert buf[-4] == 5.0

    def test_qbuffer_idx_clamped(self):
        buf = LineBuffer()
        buf.setminperiod(3)
        buf.qbuffer(savemem=True, extrasize=0)
        for v in range(10):
            buf.forward(value=float(v))
        # idx should be clamped to maxlen - 1 = 2
        assert buf.idx == 2

    def test_qbuffer_reset(self):
        buf = LineBuffer()
        buf.setminperiod(3)
        buf.qbuffer(savemem=True, extrasize=0)
        buf.forward(value=1.0)
        buf.forward(value=2.0)
        buf.reset()
        assert buf.idx == -1
        assert buf.lencount == 0

    def test_qbuffer_transfer_existing_data(self):
        """Switching to QBuffer mode preserves recent data."""
        buf = LineBuffer()
        buf.setminperiod(3)
        for v in [1.0, 2.0, 3.0, 4.0, 5.0]:
            buf.forward(value=v)
        buf.qbuffer(savemem=True, extrasize=0)
        # maxlen = 3, should keep last 3: 3.0, 4.0, 5.0
        assert buf[0] == 5.0
        assert buf[-1] == 4.0
        assert buf[-2] == 3.0


class TestLineBufferMinPeriod:
    """LineSingle-specific period management."""

    def test_setminperiod(self):
        buf = LineBuffer()
        buf.setminperiod(5)
        assert buf.minperiod == 5

    def test_updateminperiod_larger(self):
        buf = LineBuffer()
        buf.setminperiod(3)
        buf.updateminperiod(5)
        assert buf.minperiod == 5

    def test_updateminperiod_smaller_is_noop(self):
        buf = LineBuffer()
        buf.setminperiod(5)
        buf.updateminperiod(3)
        assert buf.minperiod == 5

    def test_addminperiod_subtracts_one(self):
        """LineSingle.addminperiod subtracts 1 for the overlapping bar."""
        buf = LineBuffer()
        buf.setminperiod(5)
        buf.addminperiod(3)
        # 5 + 3 - 1 = 7
        assert buf.minperiod == 7

    def test_incminperiod_no_subtraction(self):
        buf = LineBuffer()
        buf.setminperiod(5)
        buf.incminperiod(3)
        # 5 + 3 = 8
        assert buf.minperiod == 8


class TestLineBufferRepr:
    """LineBuffer repr."""

    def test_repr_unbounded(self):
        buf = LineBuffer()
        r = repr(buf)
        assert "Unbounded" in r
        assert "idx=-1" in r

    def test_repr_qbuffer(self):
        buf = LineBuffer()
        buf.setminperiod(3)
        buf.qbuffer(savemem=True)
        r = repr(buf)
        assert "QBuffer" in r
