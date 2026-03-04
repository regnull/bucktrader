"""Tests for Lines container, LineAlias, LineMultiple, and LineSeries."""

import math

import pytest

from bucktrader.lineseries import (
    AutoInfoDict,
    LineAlias,
    LineBuffer,
    LineMultiple,
    Lines,
    LineSeries,
    LinesOperation,
    NaN,
)


# ---------------------------------------------------------------------------
# Lines Container
# ---------------------------------------------------------------------------


class TestLines:
    """Lines container: holds multiple LineBuffers."""

    def test_default_lines_empty(self):
        lines = Lines()
        assert len(lines) == 0
        assert lines.getlines() == ()

    def test_indexing(self):
        MyLines = Lines.derive("MyLines", lines=("open", "close"))
        inst = MyLines()
        assert len(inst) == 2
        assert isinstance(inst[0], LineBuffer)
        assert isinstance(inst[1], LineBuffer)

    def test_iteration(self):
        MyLines = Lines.derive("MyLines", lines=("a", "b", "c"))
        inst = MyLines()
        buffers = list(inst)
        assert len(buffers) == 3
        assert all(isinstance(b, LineBuffer) for b in buffers)

    def test_forward_all(self):
        MyLines = Lines.derive("MyLines", lines=("a", "b"))
        inst = MyLines()
        inst.forward(value=42.0)
        assert inst[0][0] == 42.0
        assert inst[1][0] == 42.0

    def test_rewind_all(self):
        MyLines = Lines.derive("MyLines", lines=("a", "b"))
        inst = MyLines()
        inst.forward(value=1.0)
        inst.forward(value=2.0)
        inst.rewind(size=1)
        assert inst[0].idx == 0
        assert inst[1].idx == 0

    def test_home_all(self):
        MyLines = Lines.derive("MyLines", lines=("a", "b"))
        inst = MyLines()
        inst.forward(value=1.0)
        inst.forward(value=2.0)
        inst.home()
        assert inst[0].idx == -1
        assert inst[1].idx == -1

    def test_reset_all(self):
        MyLines = Lines.derive("MyLines", lines=("a", "b"))
        inst = MyLines()
        inst.forward(value=1.0)
        inst.reset()
        assert inst[0].idx == -1
        assert inst[0].lencount == 0


class TestLinesDerive:
    """Lines.derive() - create named Lines subclasses."""

    def test_derive_creates_subclass(self):
        MyLines = Lines.derive("MyLines", lines=("open", "close"))
        assert issubclass(MyLines, Lines)

    def test_derive_names(self):
        MyLines = Lines.derive("MyLines", lines=("open", "close", "volume"))
        assert MyLines.getlines() == ("open", "close", "volume")

    def test_derive_instantiation(self):
        MyLines = Lines.derive("MyLines", lines=("a", "b"))
        inst = MyLines()
        assert len(inst) == 2

    def test_derive_with_extralines(self):
        MyLines = Lines.derive("MyLines", lines=("a",), extralines=2)
        inst = MyLines()
        # 1 named + 2 extra = 3
        assert len(inst) == 3

    def test_derive_inherits_base_lines(self):
        Base = Lines.derive("Base", lines=("a", "b"))
        Child = Base.derive("Child", lines=("c",))
        assert "a" in Child.getlines()
        assert "b" in Child.getlines()
        assert "c" in Child.getlines()

    def test_derive_no_duplicate_lines(self):
        Base = Lines.derive("Base", lines=("a", "b"))
        Child = Base.derive("Child", lines=("b", "c"))
        names = Child.getlines()
        assert names.count("b") == 1

    def test_derive_with_otherbases(self):
        Base1 = Lines.derive("Base1", lines=("x", "y"))
        Base2 = Lines.derive("Base2", lines=("z",))
        Combined = Lines.derive("Combined", lines=("w",), otherbases=(Base1, Base2))
        names = Combined.getlines()
        assert "x" in names
        assert "y" in names
        assert "z" in names
        assert "w" in names


# ---------------------------------------------------------------------------
# LineAlias Descriptors
# ---------------------------------------------------------------------------


class TestLineAlias:
    """LineAlias descriptors for named line access on Lines container."""

    def test_named_access_get(self):
        MyLines = Lines.derive("MyLines", lines=("open", "close"))
        inst = MyLines()
        inst[0].forward(value=100.0)
        assert inst.open[0] == 100.0

    def test_named_access_different_lines(self):
        MyLines = Lines.derive("MyLines", lines=("open", "close"))
        inst = MyLines()
        inst[0].forward(value=100.0)
        inst[1].forward(value=200.0)
        assert inst.open[0] == 100.0
        assert inst.close[0] == 200.0

    def test_named_access_returns_linebuffer(self):
        MyLines = Lines.derive("MyLines", lines=("sma",))
        inst = MyLines()
        assert isinstance(inst.sma, LineBuffer)

    def test_alias_set_creates_binding(self):
        """Setting a line alias with a LineRoot creates a binding."""
        MyLines = Lines.derive("MyLines", lines=("output",))
        inst = MyLines()

        source = LineBuffer()
        inst.output = source

        # Now source has a binding to inst[0]
        assert inst[0] in source.bindings

    def test_alias_set_binding_propagates(self):
        MyLines = Lines.derive("MyLines", lines=("output",))
        inst = MyLines()

        source = LineBuffer()
        inst.output = source

        # When source gets a value, it should propagate to inst[0]
        source.forward(value=42.0)
        # inst[0] should also have been forwarded
        assert inst[0][0] == 42.0

    def test_class_level_access_returns_descriptor(self):
        MyLines = Lines.derive("MyLines", lines=("sma",))
        # Accessing on the class (not instance) returns the descriptor
        descriptor = MyLines.__dict__["sma"]
        assert isinstance(descriptor, LineAlias)


# ---------------------------------------------------------------------------
# LineMultiple
# ---------------------------------------------------------------------------


class TestLineMultiple:
    """LineMultiple: container for multiple lines with delegation."""

    def test_default_line(self):
        MyLines = Lines.derive("MyLines", lines=("a", "b"))
        inst = MyLines()
        multi = LineMultiple(lines=inst)
        assert multi.line is inst[0]

    def test_indexing_delegates_to_first_line(self):
        MyLines = Lines.derive("MyLines", lines=("a", "b"))
        inst = MyLines()
        inst[0].forward(value=99.0)
        multi = LineMultiple(lines=inst)
        assert multi[0] == 99.0

    def test_setitem_delegates_to_first_line(self):
        MyLines = Lines.derive("MyLines", lines=("a", "b"))
        inst = MyLines()
        inst[0].forward(value=0.0)
        multi = LineMultiple(lines=inst)
        multi[0] = 55.0
        assert inst[0][0] == 55.0

    def test_len_of_first_line(self):
        MyLines = Lines.derive("MyLines", lines=("a",))
        inst = MyLines()
        inst[0].forward(value=1.0)
        inst[0].forward(value=2.0)
        multi = LineMultiple(lines=inst)
        assert len(multi) == 2

    def test_stage_propagation(self):
        MyLines = Lines.derive("MyLines", lines=("a", "b"))
        inst = MyLines()
        multi = LineMultiple(lines=inst)

        multi._stage2()
        assert multi._stage == 2
        assert inst[0]._stage == 2
        assert inst[1]._stage == 2

        multi._stage1()
        assert multi._stage == 1
        assert inst[0]._stage == 1
        assert inst[1]._stage == 1

    def test_setminperiod_propagation(self):
        MyLines = Lines.derive("MyLines", lines=("a", "b"))
        inst = MyLines()
        multi = LineMultiple(lines=inst)
        multi.setminperiod(10)
        assert multi.minperiod == 10
        assert inst[0].minperiod == 10
        assert inst[1].minperiod == 10

    def test_updateminperiod_propagation(self):
        MyLines = Lines.derive("MyLines", lines=("a", "b"))
        inst = MyLines()
        multi = LineMultiple(lines=inst)
        multi.setminperiod(5)
        multi.updateminperiod(10)
        assert multi.minperiod == 10
        assert inst[0].minperiod == 10

    def test_no_lines_raises(self):
        multi = LineMultiple()
        with pytest.raises(IndexError):
            _ = multi.line


# ---------------------------------------------------------------------------
# LineSeries
# ---------------------------------------------------------------------------


class TestLineSeries:
    """LineSeries: named lines with plot metadata."""

    def test_basic_definition(self):
        class MyIndicator(LineSeries):
            lines = ("sma", "signal")

        ind = MyIndicator()
        assert "sma" in type(ind)._lines_names
        assert "signal" in type(ind)._lines_names

    def test_lines_container_created(self):
        class MyIndicator(LineSeries):
            lines = ("sma",)

        ind = MyIndicator()
        assert len(ind.lines) == 1

    def test_line_access_by_name(self):
        class MyIndicator(LineSeries):
            lines = ("sma",)

        ind = MyIndicator()
        sma = ind.sma
        assert isinstance(sma, LineBuffer)

    def test_line_access_via_lines_container(self):
        class MyIndicator(LineSeries):
            lines = ("sma", "signal")

        ind = MyIndicator()
        assert isinstance(ind.lines.sma, LineBuffer)
        assert isinstance(ind.lines.signal, LineBuffer)

    def test_write_and_read(self):
        class MyIndicator(LineSeries):
            lines = ("output",)

        ind = MyIndicator()
        ind.lines[0].forward(value=42.0)
        assert ind.output[0] == 42.0

    def test_first_line_is_default(self):
        class MyIndicator(LineSeries):
            lines = ("primary", "secondary")

        ind = MyIndicator()
        ind.lines[0].forward(value=10.0)
        assert ind[0] == 10.0

    def test_plotinfo_defaults(self):
        class MyIndicator(LineSeries):
            lines = ("sma",)

        ind = MyIndicator()
        assert ind.plotinfo.plot is True
        assert ind.plotinfo.subplot is True

    def test_plotinfo_override(self):
        class MyIndicator(LineSeries):
            lines = ("sma",)
            plotinfo = {"subplot": False, "plotname": "SMA"}

        ind = MyIndicator()
        assert ind.plotinfo.subplot is False
        assert ind.plotinfo.plotname == "SMA"

    def test_plotinfo_attribute_access(self):
        class MyIndicator(LineSeries):
            lines = ("sma",)

        ind = MyIndicator()
        # AutoInfoDict supports attribute access
        ind.plotinfo.custom_key = "value"
        assert ind.plotinfo.custom_key == "value"

    def test_inheritance(self):
        class Base(LineSeries):
            lines = ("a", "b")

        class Child(Base):
            lines = ("c",)

        child = Child()
        names = type(child)._lines_names
        assert "a" in names
        assert "b" in names
        assert "c" in names
        assert len(child.lines) >= 3

    def test_no_duplicate_lines_in_inheritance(self):
        class Base(LineSeries):
            lines = ("a", "b")

        class Child(Base):
            lines = ("b", "c")

        child = Child()
        names = type(child)._lines_names
        assert names.count("b") == 1

    def test_minperiod_default(self):
        class MyIndicator(LineSeries):
            lines = ("sma",)

        ind = MyIndicator()
        assert ind.minperiod == 1

    def test_stage_switching(self):
        class MyIndicator(LineSeries):
            lines = ("sma",)

        ind = MyIndicator()
        ind._stage2()
        assert ind._stage == 2
        ind._stage1()
        assert ind._stage == 1

    def test_repr(self):
        class MyIndicator(LineSeries):
            lines = ("sma",)

        ind = MyIndicator()
        r = repr(ind)
        assert "MyIndicator" in r
        assert "sma" in r

    def test_empty_lines(self):
        class EmptyIndicator(LineSeries):
            lines = ()

        ind = EmptyIndicator()
        assert len(ind.lines) == 0


# ---------------------------------------------------------------------------
# AutoInfoDict
# ---------------------------------------------------------------------------


class TestAutoInfoDict:
    """AutoInfoDict: dict with attribute-style access."""

    def test_attribute_access(self):
        d = AutoInfoDict({"a": 1, "b": 2})
        assert d.a == 1
        assert d.b == 2

    def test_attribute_set(self):
        d = AutoInfoDict()
        d.x = 42
        assert d["x"] == 42
        assert d.x == 42

    def test_missing_attribute_raises(self):
        d = AutoInfoDict()
        with pytest.raises(AttributeError):
            _ = d.nonexistent

    def test_from_defaults(self):
        d = AutoInfoDict.from_defaults({"key": "value"})
        assert d.key == "value"

    def test_from_defaults_none(self):
        d = AutoInfoDict.from_defaults(None)
        assert len(d) == 0


# ---------------------------------------------------------------------------
# Integration: Operator chaining through LineSeries
# ---------------------------------------------------------------------------


class TestOperatorIntegration:
    """Test that operators work through LineSeries."""

    def test_lineseries_arithmetic_creates_operation(self):
        class MySeries(LineSeries):
            lines = ("close",)

        s1 = MySeries()
        s2 = MySeries()
        result = s1 + s2
        assert isinstance(result, LinesOperation)

    def test_lineseries_stage2_comparison(self):
        class MySeries(LineSeries):
            lines = ("close",)

        s = MySeries()
        s.lines[0].forward(value=10.0)
        s._stage2()
        assert (s > 5.0) is True
        assert (s < 5.0) is False
