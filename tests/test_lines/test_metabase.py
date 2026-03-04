"""Tests for bucktrader.metabase -- Component Model and Parameter System."""

import pytest

from bucktrader.metabase import (
    AutoInfoClass,
    ComponentBase,
    IndType,
    LineAlias,
    LineIteratorBase,
    LineSeriesBase,
    MetaBase,
    MetaLineIterator,
    MetaLineSeries,
    MetaParams,
    ObsType,
    ParamsBase,
    SingletonBase,
    SingletonMeta,
    StratType,
    findowner,
)


# ======================================================================
# AutoInfoClass
# ======================================================================


class TestAutoInfoClass:
    """Tests for the dynamic key-value store."""

    def test_empty_info_class(self):
        """An underived AutoInfoClass has no params."""
        assert AutoInfoClass.getpairs() == ()
        assert AutoInfoClass.getkeys() == ()
        assert AutoInfoClass.getdefaults() == ()

    def test_derive_creates_subclass(self):
        """derive() produces a new subclass with the given pairs."""
        Info = AutoInfoClass.derive("Info", [("period", 10), ("factor", 2.0)])
        assert issubclass(Info, AutoInfoClass)
        assert Info.getkeys() == ("period", "factor")
        assert Info.getdefaults() == (10, 2.0)

    def test_derive_preserves_parent(self):
        """Deriving does not mutate the parent."""
        Parent = AutoInfoClass.derive("Parent", [("a", 1)])
        _Child = Parent.derive("Child", [("b", 2)])
        # Parent should still have only 'a'
        assert Parent.getkeys() == ("a",)
        assert Parent.getdefaults() == (1,)

    def test_derive_inherits_parent_params(self):
        """A child class inherits parent params and can add its own."""
        Parent = AutoInfoClass.derive("Parent", [("period", 10)])
        Child = Parent.derive("Child", [("factor", 2.0)])
        assert Child.getkeys() == ("period", "factor")
        assert Child.getdefaults() == (10, 2.0)

    def test_derive_overrides_parent_default(self):
        """A child can override a parent's default value."""
        Parent = AutoInfoClass.derive("Parent", [("period", 10)])
        Child = Parent.derive("Child", [("period", 20)])
        assert Child.getkeys() == ("period",)
        assert Child.getdefaults() == (20,)
        # Parent unchanged
        assert Parent.getdefaults() == (10,)

    def test_instance_uses_defaults(self):
        """Instances use class-level defaults when no overrides given."""
        Info = AutoInfoClass.derive("Info", [("period", 10), ("factor", 2.0)])
        inst = Info()
        assert inst.period == 10
        assert inst.factor == 2.0

    def test_instance_override(self):
        """Instances can override defaults via keyword arguments."""
        Info = AutoInfoClass.derive("Info", [("period", 10), ("factor", 2.0)])
        inst = Info(period=30)
        assert inst.period == 30
        assert inst.factor == 2.0  # unchanged

    def test_instance_override_all(self):
        """All defaults can be overridden simultaneously."""
        Info = AutoInfoClass.derive("Info", [("period", 10), ("factor", 2.0)])
        inst = Info(period=50, factor=3.5)
        assert inst.period == 50
        assert inst.factor == 3.5

    def test_instance_unexpected_kwarg(self):
        """Unexpected keyword arguments raise TypeError."""
        Info = AutoInfoClass.derive("Info", [("period", 10)])
        with pytest.raises(TypeError, match="Unexpected keyword"):
            Info(unknown=42)

    def test_getpairs_class_level(self):
        """getpairs() works at the class level."""
        Info = AutoInfoClass.derive("Info", [("a", 1), ("b", 2)])
        assert Info.getpairs() == (("a", 1), ("b", 2))

    def test_getitems_instance_level(self):
        """getitems() returns (name, current_value) on an instance."""
        Info = AutoInfoClass.derive("Info", [("x", 10), ("y", 20)])
        inst = Info(x=99)
        assert inst.getitems() == (("x", 99), ("y", 20))

    def test_getvalues_instance_level(self):
        """getvalues() returns current values on an instance."""
        Info = AutoInfoClass.derive("Info", [("x", 10), ("y", 20)])
        inst = Info(y=42)
        assert inst.getvalues() == (10, 42)

    def test_setattr_invalid_param(self):
        """Setting an attribute not in _params raises AttributeError."""
        Info = AutoInfoClass.derive("Info", [("period", 10)])
        inst = Info()
        with pytest.raises(AttributeError, match="no parameter"):
            inst.bad_attr = 5

    def test_setattr_valid_param(self):
        """Existing params can be mutated after creation."""
        Info = AutoInfoClass.derive("Info", [("period", 10)])
        inst = Info()
        inst.period = 42
        assert inst.period == 42

    def test_repr(self):
        """__repr__ shows the class name and current values."""
        Info = AutoInfoClass.derive("Info", [("period", 10)])
        inst = Info(period=30)
        assert "Info" in repr(inst)
        assert "period=30" in repr(inst)

    def test_multi_level_inheritance(self):
        """Three-level inheritance works correctly."""
        A = AutoInfoClass.derive("A", [("a", 1)])
        B = A.derive("B", [("b", 2)])
        C = B.derive("C", [("c", 3), ("a", 99)])
        assert C.getkeys() == ("a", "b", "c")
        assert C.getdefaults() == (99, 2, 3)

    def test_derive_empty(self):
        """derive() with no new pairs produces an identical copy."""
        Parent = AutoInfoClass.derive("Parent", [("x", 10)])
        Child = Parent.derive("Child")
        assert Child.getkeys() == ("x",)
        assert Child.getdefaults() == (10,)


# ======================================================================
# Component type constants
# ======================================================================


class TestComponentTypeConstants:
    """Tests for IndType, StratType, ObsType."""

    def test_constants_are_ints(self):
        assert isinstance(IndType, int)
        assert isinstance(StratType, int)
        assert isinstance(ObsType, int)

    def test_constant_values(self):
        assert IndType == 0
        assert StratType == 1
        assert ObsType == 2

    def test_constants_are_distinct(self):
        assert len({IndType, StratType, ObsType}) == 3


# ======================================================================
# MetaBase -- Lifecycle hooks
# ======================================================================


class TestMetaBase:
    """Tests for the MetaBase lifecycle protocol."""

    def test_basic_creation(self):
        """Classes with MetaBase can be instantiated."""

        class MyComponent(metaclass=MetaBase):
            def __init__(self):
                self.initialized = True

        obj = MyComponent()
        assert obj.initialized is True

    def test_lifecycle_hook_order(self):
        """Hooks are called in the correct order."""
        call_log = []

        class TrackingMeta(MetaBase):
            def doprenew(cls, *args, **kwargs):
                call_log.append("doprenew")
                return super().doprenew(*args, **kwargs)

            def donew(cls, obj, *args, **kwargs):
                call_log.append("donew")
                return super().donew(obj, *args, **kwargs)

            def dopreinit(cls, obj, *args, **kwargs):
                call_log.append("dopreinit")
                return super().dopreinit(obj, *args, **kwargs)

            def doinit(cls, obj, *args, **kwargs):
                call_log.append("doinit")
                return super().doinit(obj, *args, **kwargs)

            def dopostinit(cls, obj, *args, **kwargs):
                call_log.append("dopostinit")
                return super().dopostinit(obj, *args, **kwargs)

        class Comp(metaclass=TrackingMeta):
            pass

        Comp()
        assert call_log == [
            "doprenew",
            "donew",
            "dopreinit",
            "doinit",
            "dopostinit",
        ]

    def test_args_passed_to_init(self):
        """Arguments are forwarded through the lifecycle to __init__."""

        class Comp(metaclass=MetaBase):
            def __init__(self, value):
                self.value = value

        obj = Comp(42)
        assert obj.value == 42

    def test_kwargs_passed_to_init(self):
        """Keyword arguments are forwarded through to __init__."""

        class Comp(metaclass=MetaBase):
            def __init__(self, name="default"):
                self.name = name

        obj = Comp(name="custom")
        assert obj.name == "custom"

    def test_hook_can_modify_args(self):
        """A hook can modify args before they reach __init__."""

        class ModifyingMeta(MetaBase):
            def donew(cls, obj, *args, **kwargs):
                # Inject an extra kwarg
                kwargs["injected"] = True
                return super().donew(obj, *args, **kwargs)

        class Comp(metaclass=ModifyingMeta):
            def __init__(self, injected=False):
                self.injected = injected

        obj = Comp()
        assert obj.injected is True


# ======================================================================
# MetaParams -- Parameter processing
# ======================================================================


class TestMetaParams:
    """Tests for parameter declaration and inheritance."""

    def test_basic_params(self):
        """Simple params declaration works."""

        class MyComp(metaclass=MetaParams):
            params = (("period", 10), ("factor", 2.0))

            def __init__(self):
                pass

        obj = MyComp()
        assert obj.params.period == 10
        assert obj.params.factor == 2.0

    def test_shorthand_alias(self):
        """obj.p is the same as obj.params."""

        class MyComp(metaclass=MetaParams):
            params = (("period", 10),)

            def __init__(self):
                pass

        obj = MyComp()
        assert obj.p is obj.params
        assert obj.p.period == 10

    def test_param_override_at_instantiation(self):
        """Params can be overridden when creating an instance."""

        class MyComp(metaclass=MetaParams):
            params = (("period", 10),)

            def __init__(self):
                pass

        obj = MyComp(period=30)
        assert obj.params.period == 30

    def test_param_inheritance(self):
        """Subclasses inherit parent params."""

        class Base(metaclass=MetaParams):
            params = (("period", 10),)

            def __init__(self):
                pass

        class Derived(Base):
            params = (("factor", 2.0),)

        obj = Derived()
        assert obj.params.period == 10
        assert obj.params.factor == 2.0

    def test_param_override_in_subclass(self):
        """Subclasses can override parent default values."""

        class Base(metaclass=MetaParams):
            params = (("period", 10),)

            def __init__(self):
                pass

        class Derived(Base):
            params = (("period", 20),)

        base_obj = Base()
        derived_obj = Derived()
        assert base_obj.params.period == 10
        assert derived_obj.params.period == 20

    def test_no_params(self):
        """Classes without params still get an empty params object."""

        class Bare(metaclass=MetaParams):
            def __init__(self):
                pass

        obj = Bare()
        assert obj.params.getkeys() == ()

    def test_params_class_isolation(self):
        """Each class gets its own _params_class; they don't share state."""

        class A(metaclass=MetaParams):
            params = (("a", 1),)

            def __init__(self):
                pass

        class B(metaclass=MetaParams):
            params = (("b", 2),)

            def __init__(self):
                pass

        a = A()
        b = B()
        assert a.params.getkeys() == ("a",)
        assert b.params.getkeys() == ("b",)

    def test_param_kwarg_separated_from_init_kwargs(self):
        """Param kwargs are consumed; remaining kwargs go to __init__."""

        class MyComp(metaclass=MetaParams):
            params = (("period", 10),)

            def __init__(self, extra="default"):
                self.extra = extra

        obj = MyComp(period=30, extra="custom")
        assert obj.params.period == 30
        assert obj.extra == "custom"


# ======================================================================
# MetaParams -- Dependency imports
# ======================================================================


class TestDependencyImports:
    """Tests for packages and frompackages resolution."""

    def test_packages_import(self):
        """The 'packages' attribute imports a module as a class attr."""

        class MyComp(metaclass=MetaParams):
            packages = ("math",)

            def __init__(self):
                pass

        import math
        assert MyComp.math is math

    def test_frompackages_import(self):
        """The 'frompackages' attribute does selective imports."""

        class MyComp(metaclass=MetaParams):
            frompackages = (("math", ("sqrt", "floor")),)

            def __init__(self):
                pass

        import math
        assert MyComp.sqrt is math.sqrt
        assert MyComp.floor is math.floor

    def test_missing_package_is_graceful(self):
        """Missing optional packages do not raise errors."""

        class MyComp(metaclass=MetaParams):
            packages = ("nonexistent_package_xyz",)

            def __init__(self):
                pass

        # Should not raise
        obj = MyComp()
        assert not hasattr(MyComp, "nonexistent_package_xyz")


# ======================================================================
# findowner -- Stack-based owner discovery
# ======================================================================


class TestFindOwner:
    """Tests for the findowner utility."""

    def test_finds_owner_in_caller_locals(self):
        """findowner locates an object of the given class in the call stack."""

        class Owner:
            pass

        class Child:
            pass

        owner = Owner()  # noqa: F841 -- must exist in locals
        child = Child()
        # findowner with startlevel=1 to look at our frame
        found = findowner(child, Owner, startlevel=1)
        assert found is owner

    def test_returns_none_when_no_owner(self):
        """findowner returns None when no matching owner exists."""

        class Owner:
            pass

        class Child:
            pass

        child = Child()
        found = findowner(child, Owner, startlevel=1)
        assert found is None

    def test_skip_parameter(self):
        """findowner skips the specified object."""

        class Base:
            pass

        owner1 = Base()
        owner2 = Base()  # noqa: F841
        found = findowner(None, Base, startlevel=1, skip=owner1)
        # Should find owner2 (not owner1)
        assert found is not owner1
        assert found is owner2

    def test_finds_in_nested_call(self):
        """findowner works across nested function calls."""

        class Owner:
            pass

        class Child:
            pass

        def create_child():
            child = Child()
            return findowner(child, Owner, startlevel=1)

        owner = Owner()  # noqa: F841 -- must exist in locals
        found = create_child()
        assert found is owner


# ======================================================================
# MetaLineSeries -- Line declaration
# ======================================================================


class TestMetaLineSeries:
    """Tests for line declaration and LineAlias descriptors."""

    def test_line_names_stored(self):
        """Declared line names are stored on the class."""

        class MyInd(metaclass=MetaLineSeries):
            lines = ("sma", "signal")

            def __init__(self):
                pass

        assert "sma" in MyInd._line_names
        assert "signal" in MyInd._line_names

    def test_line_alias_descriptor_exists(self):
        """LineAlias descriptors are created for each line name."""

        class MyInd(metaclass=MetaLineSeries):
            lines = ("sma",)

            def __init__(self):
                pass

        # Access on the class returns the descriptor itself
        assert isinstance(MyInd.__dict__.get("sma"), LineAlias)

    def test_line_inheritance(self):
        """Subclasses inherit parent lines."""

        class Base(metaclass=MetaLineSeries):
            lines = ("line_a",)

            def __init__(self):
                pass

        class Child(Base):
            lines = ("line_b",)

        assert "line_a" in Child._line_names
        assert "line_b" in Child._line_names

    def test_plotinfo_class_created(self):
        """plotinfo is processed into an AutoInfoClass."""

        class MyInd(metaclass=MetaLineSeries):
            plotinfo = (("subplot", True), ("plotname", "SMA"))

            def __init__(self):
                pass

        assert MyInd._plotinfo_class.getkeys() == ("subplot", "plotname")

    def test_alias_stored(self):
        """Class aliases are stored."""

        class SMA(metaclass=MetaLineSeries):
            alias = ("SimpleMovingAverage", "MovAvgSimple")

            def __init__(self):
                pass

        assert "SimpleMovingAverage" in SMA._cls_aliases
        assert "MovAvgSimple" in SMA._cls_aliases

    def test_no_lines_is_fine(self):
        """A class with no lines declaration works fine."""

        class Bare(metaclass=MetaLineSeries):
            def __init__(self):
                pass

        assert Bare._line_names == ()


# ======================================================================
# LineAlias
# ======================================================================


class TestLineAlias:
    """Tests for the LineAlias descriptor."""

    def test_line_alias_get(self):
        """LineAlias.__get__ returns the corresponding line from obj.lines."""

        class FakeObj:
            lines = ["line0", "line1", "line2"]

        alias = LineAlias(1)
        obj = FakeObj()
        assert alias.__get__(obj) == "line1"

    def test_line_alias_get_on_class(self):
        """Accessing LineAlias on the class returns the descriptor itself."""
        alias = LineAlias(0)
        result = alias.__get__(None, type)
        assert result is alias


# ======================================================================
# MetaLineIterator -- Data discovery and auto-registration
# ======================================================================


class TestMetaLineIterator:
    """Tests for data discovery, clock setup, and child management."""

    def test_lineiterators_initialized(self):
        """_lineiterators dict is created with all three component types."""

        class MyComp(metaclass=MetaLineIterator):
            def __init__(self):
                pass

        obj = MyComp()
        assert IndType in obj._lineiterators
        assert StratType in obj._lineiterators
        assert ObsType in obj._lineiterators

    def test_datas_list_created(self):
        """obj.datas is always created (even if empty)."""

        class MyComp(metaclass=MetaLineIterator):
            def __init__(self):
                pass

        obj = MyComp()
        assert isinstance(obj.datas, list)

    def test_data_convenience_none_when_no_datas(self):
        """obj.data is None when no data feeds are provided."""

        class MyComp(metaclass=MetaLineIterator):
            def __init__(self):
                pass

        obj = MyComp()
        assert obj.data is None

    def test_minperiod_defaults_to_one(self):
        """Default minimum period is 1."""

        class MyComp(metaclass=MetaLineIterator):
            def __init__(self):
                pass

        obj = MyComp()
        assert obj._minperiod == 1

    def test_dnames_created(self):
        """Named data feeds map is created."""

        class MyComp(metaclass=MetaLineIterator):
            def __init__(self):
                pass

        obj = MyComp()
        assert isinstance(obj.dnames, dict)


# ======================================================================
# LineIteratorBase -- Convenience base class
# ======================================================================


class TestLineIteratorBase:
    """Tests for the convenience LineIteratorBase."""

    def test_addindicator(self):
        """addindicator() adds to IndType list."""
        parent = LineIteratorBase()
        child = LineIteratorBase()
        parent.addindicator(child)
        assert child in parent._lineiterators[IndType]

    def test_addobserver(self):
        """addobserver() adds to ObsType list."""
        parent = LineIteratorBase()
        child = LineIteratorBase()
        parent.addobserver(child)
        assert child in parent._lineiterators[ObsType]

    def test_addstrategy(self):
        """addstrategy() adds to StratType list."""
        parent = LineIteratorBase()
        child = LineIteratorBase()
        parent.addstrategy(child)
        assert child in parent._lineiterators[StratType]


# ======================================================================
# SingletonMeta
# ======================================================================


class TestSingletonMeta:
    """Tests for the Singleton metaclass."""

    def test_single_instance(self):
        """Only one instance is created per class."""

        class MyStore(metaclass=SingletonMeta):
            def __init__(self):
                self.value = 42

        a = MyStore()
        b = MyStore()
        assert a is b

    def test_different_classes_different_singletons(self):
        """Different classes get their own singletons."""

        class StoreA(metaclass=SingletonMeta):
            def __init__(self):
                self.kind = "A"

        class StoreB(metaclass=SingletonMeta):
            def __init__(self):
                self.kind = "B"

        a = StoreA()
        b = StoreB()
        assert a is not b
        assert a.kind == "A"
        assert b.kind == "B"

    def test_singleton_with_params(self):
        """Singleton classes can have params (via MetaParams)."""

        class MyStore(metaclass=SingletonMeta):
            params = (("host", "localhost"),)

            def __init__(self):
                pass

        a = MyStore()
        b = MyStore()
        assert a is b
        assert a.params.host == "localhost"


# ======================================================================
# ParamsBase -- Convenience base class
# ======================================================================


class TestParamsBase:
    """Tests for the ParamsBase convenience class."""

    def test_inheriting_from_paramsbase(self):
        """User classes can inherit from ParamsBase for params support."""

        class MyComponent(ParamsBase):
            params = (("period", 10), ("multiplier", 1.5))

            def __init__(self):
                pass

        obj = MyComponent(period=25)
        assert obj.p.period == 25
        assert obj.p.multiplier == 1.5

    def test_paramsbase_hierarchy(self):
        """Multi-level inheritance through ParamsBase works."""

        class Base(ParamsBase):
            params = (("a", 1),)

            def __init__(self):
                pass

        class Mid(Base):
            params = (("b", 2),)

        class Leaf(Mid):
            params = (("c", 3), ("a", 10))

        obj = Leaf()
        assert obj.p.a == 10
        assert obj.p.b == 2
        assert obj.p.c == 3


# ======================================================================
# ComponentBase -- Convenience base class
# ======================================================================


class TestComponentBase:
    """Tests for the ComponentBase convenience class."""

    def test_basic_creation(self):
        """ComponentBase instances can be created."""

        class Simple(ComponentBase):
            def __init__(self):
                self.ready = True

        obj = Simple()
        assert obj.ready is True


# ======================================================================
# Integration scenarios
# ======================================================================


class TestIntegration:
    """Integration tests exercising multiple pieces together."""

    def test_params_with_lines_declaration(self):
        """A class with both params and lines declarations works."""

        class MyIndicator(metaclass=MetaLineSeries):
            params = (("period", 20), ("devfactor", 2.0))
            lines = ("upper", "middle", "lower")

            def __init__(self):
                pass

        obj = MyIndicator(period=30)
        assert obj.params.period == 30
        assert obj.params.devfactor == 2.0
        assert "upper" in MyIndicator._line_names
        assert "middle" in MyIndicator._line_names
        assert "lower" in MyIndicator._line_names

    def test_full_iterator_with_params_and_lines(self):
        """MetaLineIterator class with params and lines works end-to-end."""

        class MyStrategy(metaclass=MetaLineIterator):
            params = (("fast", 10), ("slow", 30))
            lines = ("signal",)

            def __init__(self):
                pass

        obj = MyStrategy(fast=5)
        assert obj.p.fast == 5
        assert obj.p.slow == 30
        assert "signal" in MyStrategy._line_names
        assert obj._minperiod == 1
        assert obj._lineiterators[IndType] == []

    def test_findowner_in_creation_context(self):
        """findowner works when an object is created inside an owner method."""

        class Owner:
            def create_child(self):
                return findowner(None, Owner, startlevel=1)

        owner = Owner()
        found = owner.create_child()
        assert found is owner

    def test_singleton_reset(self):
        """Singletons can be reset by clearing _singleton."""

        class Store(metaclass=SingletonMeta):
            def __init__(self):
                self.count = 0

        a = Store()
        a.count = 5
        # Reset the singleton
        Store._singleton = None
        b = Store()
        assert b is not a
        assert b.count == 0
