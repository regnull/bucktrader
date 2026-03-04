"""Component Model and Parameter System for Bucktrader.

This module implements the metaclass infrastructure that powers Bucktrader's
declarative component system. Users declare lines and params as class-level
attributes; the metaclass machinery handles lifecycle management, parameter
inheritance, auto-registration, and owner discovery.

Hierarchy:
    MetaBase          -- Foundation lifecycle hooks
    MetaParams        -- Parameter processing (extends MetaBase)
    MetaLineSeries    -- Line declaration and descriptors (extends MetaParams)
    MetaLineIterator  -- Data discovery, auto-registration (extends MetaLineSeries)

Additionally:
    AutoInfoClass  -- Dynamic key-value store for params/plotinfo
    findowner()    -- Stack-based owner discovery
    SingletonMeta  -- Ensures one instance per class (for Stores)
"""

import inspect
from collections import OrderedDict

# ---------------------------------------------------------------------------
# Component type constants
# ---------------------------------------------------------------------------

IndType = 0   # Indicator
StratType = 1  # Strategy
ObsType = 2   # Observer


# ---------------------------------------------------------------------------
# AutoInfoClass -- Dynamic key-value store with inheritance
# ---------------------------------------------------------------------------

class AutoInfoClass:
    """Dynamic type storing key-value pairs as class-level defaults.

    Each subclass carries its own _params OrderedDict of (name, default) pairs.
    Instances can override defaults via keyword arguments passed at creation.

    Users should not instantiate this class directly; instead, call
    ``AutoInfoClass.derive(name, newpairs)`` to create a derived info type
    that extends the parent's pairs.
    """

    # Class-level registry of parameter (name, default) pairs.
    _params: OrderedDict = OrderedDict()

    # ------------------------------------------------------------------
    # Derivation -- create a child info class that inherits parent pairs
    # ------------------------------------------------------------------

    @classmethod
    def derive(cls, name, newpairs=None):
        """Create a derived AutoInfoClass that extends parent params.

        Args:
            name: Name for the new class (used only for repr).
            newpairs: Iterable of (name, default) pairs to add/override.

        Returns:
            A new AutoInfoClass subclass with merged parameters.
        """
        # Start from a copy of the parent params
        merged = OrderedDict(cls._params)

        if newpairs:
            for key, default in newpairs:
                merged[key] = default

        # Build a new subclass with the merged params
        new_cls = type(name, (cls,), {"_params": merged})
        return new_cls

    # ------------------------------------------------------------------
    # Instance creation -- override defaults with kwargs
    # ------------------------------------------------------------------

    def __init__(self, **kwargs):
        # Start with class-level defaults, then override with kwargs.
        for key, default in self._params.items():
            value = kwargs.pop(key, default)
            object.__setattr__(self, key, value)

        if kwargs:
            raise TypeError(
                f"Unexpected keyword arguments: {', '.join(kwargs.keys())}"
            )

    # ------------------------------------------------------------------
    # Query methods (work at both class and instance level)
    # ------------------------------------------------------------------

    @classmethod
    def getpairs(cls):
        """Return all (name, default) pairs as a tuple of tuples."""
        return tuple(cls._params.items())

    @classmethod
    def getkeys(cls):
        """Return parameter names as a tuple."""
        return tuple(cls._params.keys())

    @classmethod
    def getdefaults(cls):
        """Return default values as a tuple."""
        return tuple(cls._params.values())

    def getitems(self):
        """Return (name, current_value) pairs for this instance."""
        return tuple(
            (key, getattr(self, key)) for key in self._params
        )

    def getvalues(self):
        """Return current values for this instance."""
        return tuple(getattr(self, key) for key in self._params)

    # ------------------------------------------------------------------
    # Attribute access safety
    # ------------------------------------------------------------------

    def __setattr__(self, name, value):
        if name not in self._params:
            raise AttributeError(
                f"'{type(self).__name__}' has no parameter '{name}'"
            )
        object.__setattr__(self, name, value)

    def __repr__(self):
        items = ", ".join(f"{k}={getattr(self, k)!r}" for k in self._params)
        return f"{type(self).__name__}({items})"


# ---------------------------------------------------------------------------
# findowner -- Stack-based owner discovery
# ---------------------------------------------------------------------------

def findowner(owned, cls, startlevel=2, skip=None):
    """Traverse the Python call stack to find an owning object.

    Walks up the call stack examining local variables for an instance of
    *cls*. Used by indicators to find their owning strategy and by
    strategies to find their owning Cortex.

    Args:
        owned: The object looking for its owner (unused in search logic
               but kept for API symmetry and potential future use).
        cls: The class the owner must be an instance of.
        startlevel: Stack frame level to begin searching (default 2 to
                    skip findowner itself and the immediate caller).
        skip: An object to skip if encountered (e.g., to avoid matching
              the owned object itself when it is also an instance of cls).

    Returns:
        The first matching owner object, or None if not found.
    """
    frames = inspect.stack()

    for frame_info in frames[startlevel:]:
        local_vars = frame_info[0].f_locals
        for obj in local_vars.values():
            if skip is not None and obj is skip:
                continue
            if isinstance(obj, cls):
                return obj

    return None


# ---------------------------------------------------------------------------
# MetaBase -- Foundation metaclass with lifecycle hooks
# ---------------------------------------------------------------------------

class MetaBase(type):
    """Foundation metaclass implementing the multi-phase creation protocol.

    When a class using this metaclass is instantiated, the following hooks
    are called in order:

        doprenew  -> donew -> dopreinit -> doinit -> dopostinit

    Each hook receives (cls, obj, *args, **kwargs) and returns
    (obj, args, kwargs), allowing any phase to modify the object or
    its arguments before the next phase.
    """

    def __call__(cls, *args, **kwargs):
        """Orchestrate the full creation protocol."""
        # Phase 1: Pre-new -- can modify args/kwargs before allocation
        obj, args, kwargs = cls.doprenew(*args, **kwargs)

        # Phase 2: New -- allocate and do basic field setup
        obj, args, kwargs = cls.donew(obj, *args, **kwargs)

        # Phase 3: Pre-init -- setup before __init__
        obj, args, kwargs = cls.dopreinit(obj, *args, **kwargs)

        # Phase 4: Init -- call the user's __init__
        obj, args, kwargs = cls.doinit(obj, *args, **kwargs)

        # Phase 5: Post-init -- registration and finalization
        obj, args, kwargs = cls.dopostinit(obj, *args, **kwargs)

        return obj

    def doprenew(cls, *args, **kwargs):
        """Pre-new hook. Create an uninitialized instance.

        Returns:
            Tuple of (obj, args, kwargs).
        """
        obj = cls.__new__(cls)
        return obj, args, kwargs

    def donew(cls, obj, *args, **kwargs):
        """Object creation hook. Basic field setup.

        Returns:
            Tuple of (obj, args, kwargs).
        """
        return obj, args, kwargs

    def dopreinit(cls, obj, *args, **kwargs):
        """Pre-init hook. Setup before __init__.

        Returns:
            Tuple of (obj, args, kwargs).
        """
        return obj, args, kwargs

    def doinit(cls, obj, *args, **kwargs):
        """Init hook. Calls the user's __init__.

        Returns:
            Tuple of (obj, args, kwargs).
        """
        obj.__init__(*args, **kwargs)
        return obj, args, kwargs

    def dopostinit(cls, obj, *args, **kwargs):
        """Post-init hook. Registration and finalization.

        Returns:
            Tuple of (obj, args, kwargs).
        """
        return obj, args, kwargs


# ---------------------------------------------------------------------------
# MetaParams -- Parameter processing metaclass
# ---------------------------------------------------------------------------

class MetaParams(MetaBase):
    """Metaclass that processes ``params`` tuples on class definition.

    When a new class is defined with ``params = (("period", 10), ...)``,
    this metaclass:

    1. Collects the params tuple from the class body.
    2. Derives a new AutoInfoClass subclass that inherits the parent's
       params and adds/overrides with the new pairs.
    3. Stores the derived params class as ``cls._params_class``.
    4. During instantiation (donew), creates a params instance with any
       keyword overrides and attaches it as ``obj.params`` and ``obj.p``.

    Dependency imports via ``packages`` and ``frompackages`` class
    attributes are also resolved during class creation.
    """

    def __new__(mcs, name, bases, namespace):
        # Extract params declaration from the class body
        newparams = namespace.pop("params", ())

        # Extract dependency import declarations
        packages = namespace.pop("packages", ())
        frompackages = namespace.pop("frompackages", ())

        # Create the class first
        cls = super().__new__(mcs, name, bases, namespace)

        # Find the parent's params class (walk MRO)
        parent_params = AutoInfoClass
        for base in cls.__mro__[1:]:
            if hasattr(base, "_params_class"):
                parent_params = base._params_class
                break

        # Derive a new params class that extends the parent
        cls._params_class = parent_params.derive(
            f"{name}_params", newparams
        )

        # Resolve dependency imports
        _resolve_imports(cls, packages, frompackages)

        return cls

    def donew(cls, obj, *args, **kwargs):
        """Create params instance with keyword overrides."""
        obj, args, kwargs = super().donew(obj, *args, **kwargs)

        # Separate param kwargs from other kwargs
        param_keys = cls._params_class.getkeys()
        param_kwargs = {}
        remaining_kwargs = {}
        for key, value in kwargs.items():
            if key in param_keys:
                param_kwargs[key] = value
            else:
                remaining_kwargs[key] = value

        # Instantiate params with overrides
        obj.params = cls._params_class(**param_kwargs)
        obj.p = obj.params  # Shorthand alias

        return obj, args, remaining_kwargs


def _resolve_imports(cls, packages, frompackages):
    """Resolve dependency imports and attach to the class.

    Args:
        cls: The class being created.
        packages: Iterable of module names to import wholesale.
        frompackages: Iterable of (module_name, [names]) for selective import.
    """
    import importlib

    for pkg_name in packages:
        try:
            mod = importlib.import_module(pkg_name)
            setattr(cls, pkg_name, mod)
        except ImportError:
            pass  # Graceful degradation -- missing optional deps

    for pkg_spec in frompackages:
        if isinstance(pkg_spec, (tuple, list)) and len(pkg_spec) == 2:
            mod_name, names = pkg_spec
            try:
                mod = importlib.import_module(mod_name)
                for attr_name in names:
                    setattr(cls, attr_name, getattr(mod, attr_name))
            except (ImportError, AttributeError):
                pass


# ---------------------------------------------------------------------------
# LineAlias descriptor
# ---------------------------------------------------------------------------

class LineAlias:
    """Descriptor providing named access to a specific line by index.

    Placed on component classes so that ``obj.sma`` resolves to
    ``obj.lines[line_index]``.
    """

    def __init__(self, line_index):
        self.line_index = line_index

    def __get__(self, obj, objtype=None):
        if obj is None:
            return self
        return obj.lines[self.line_index]

    def __set__(self, obj, value):
        # Setting a line alias creates a binding from value to the target.
        target_line = obj.lines[self.line_index]
        if hasattr(value, "addbinding"):
            value.addbinding(target_line)
        else:
            # Direct value assignment -- store in the line
            target_line[0] = value


# ---------------------------------------------------------------------------
# MetaLineSeries -- Line declaration metaclass
# ---------------------------------------------------------------------------

class MetaLineSeries(MetaParams):
    """Metaclass that processes ``lines`` tuples and plot configuration.

    When a class defines ``lines = ("sma", "signal")``, this metaclass:

    1. Calls ``Lines.derive()`` to create a new Lines container subtype.
    2. Adds ``LineAlias`` descriptors on the class for each line name.
    3. Processes ``plotinfo`` and ``plotlines`` into AutoInfoClass subtypes.
    4. Registers class aliases if an ``alias`` attribute is provided.
    """

    def __new__(mcs, name, bases, namespace):
        # Extract lines declaration
        newlines = namespace.pop("lines", ())
        # Extract alias declaration
        alias = namespace.pop("alias", ())
        # Extract plotinfo and plotlines
        newplotinfo = namespace.pop("plotinfo", ())
        newplotlines = namespace.pop("plotlines", ())

        # Create the class (MetaParams.__new__ handles params)
        cls = super().__new__(mcs, name, bases, namespace)

        # ------------------------------------------------------------------
        # Process lines
        # ------------------------------------------------------------------
        line_names = []
        line_aliases = {}  # {alias_name: primary_index}

        for item in newlines:
            if isinstance(item, (tuple, list)):
                # First element is the primary name; rest are aliases
                primary = item[0]
                line_names.append(primary)
                idx = len(line_names) - 1
                for alt in item[1:]:
                    if isinstance(alt, (tuple, list)):
                        for a in alt:
                            line_aliases[a] = idx
                    else:
                        line_aliases[alt] = idx
            else:
                line_names.append(item)

        # Collect parent line names from MRO
        parent_line_names = ()
        parent_lines_class = None
        for base in cls.__mro__[1:]:
            if hasattr(base, "_lines_class"):
                parent_lines_class = base._lines_class
                parent_line_names = getattr(base, "_line_names", ())
                break

        # Store full line names (parent + new)
        all_line_names = tuple(parent_line_names) + tuple(line_names)
        cls._line_names = all_line_names
        cls._own_line_names = tuple(line_names)

        # Derive a Lines container class using lineseries (deferred import).
        # If lineseries is not available yet, store info for later.
        try:
            from bucktrader.lineseries import Lines

            base_lines_cls = parent_lines_class or Lines
            cls._lines_class = base_lines_cls.derive(
                name,
                lines=tuple(line_names),
                extralines=0,
                otherbases=(),
            )
        except ImportError:
            # lineseries not yet available -- store a placeholder
            cls._lines_class = None

        # Add LineAlias descriptors for all line names (parent + own)
        for idx, lname in enumerate(all_line_names):
            setattr(cls, lname, LineAlias(idx))

        # Add descriptors for aliases
        for alias_name, idx in line_aliases.items():
            # Alias index is relative to new lines, offset by parent count
            absolute_idx = len(parent_line_names) + idx
            setattr(cls, alias_name, LineAlias(absolute_idx))

        # ------------------------------------------------------------------
        # Process plotinfo
        # ------------------------------------------------------------------
        parent_plotinfo = AutoInfoClass
        for base in cls.__mro__[1:]:
            if hasattr(base, "_plotinfo_class"):
                parent_plotinfo = base._plotinfo_class
                break

        cls._plotinfo_class = parent_plotinfo.derive(
            f"{name}_plotinfo", newplotinfo
        )

        # ------------------------------------------------------------------
        # Process plotlines
        # ------------------------------------------------------------------
        parent_plotlines = AutoInfoClass
        for base in cls.__mro__[1:]:
            if hasattr(base, "_plotlines_class"):
                parent_plotlines = base._plotlines_class
                break

        cls._plotlines_class = parent_plotlines.derive(
            f"{name}_plotlines", newplotlines
        )

        # ------------------------------------------------------------------
        # Register class aliases
        # ------------------------------------------------------------------
        cls._cls_aliases = tuple(alias) if alias else ()

        return cls


# ---------------------------------------------------------------------------
# MetaLineIterator -- Data discovery and auto-registration metaclass
# ---------------------------------------------------------------------------

class MetaLineIterator(MetaLineSeries):
    """Metaclass adding data discovery and auto-registration to LineSeries.

    Hooks:
        donew      -- Scan args for LineRoot objects, store in obj.datas.
        dopreinit  -- Clock setup and initial period calculation.
        dopostinit -- Period recalculation and owner registration.
    """

    def donew(cls, obj, *args, **kwargs):
        """Data discovery: scan args for line-aware objects."""
        obj, args, kwargs = super().donew(obj, *args, **kwargs)

        # Initialize child iterator collections
        obj._lineiterators = {
            IndType: [],
            StratType: [],
            ObsType: [],
        }

        # Scan args for LineRoot instances
        obj.datas = []
        remaining_args = []

        for arg in args:
            if _is_line_root(arg):
                obj.datas.append(arg)
            else:
                remaining_args.append(arg)

        # Also check kwargs for line root objects
        for key, value in list(kwargs.items()):
            if _is_line_root(value):
                obj.datas.append(value)

        # Create convenience attributes
        if obj.datas:
            obj.data = obj.datas[0]
        else:
            obj.data = None

        for idx, d in enumerate(obj.datas):
            setattr(obj, f"data{idx}", d)

        # Named data feeds map
        obj.dnames = {}
        for d in obj.datas:
            dname = getattr(d, "_name", None)
            if dname:
                obj.dnames[dname] = d

        # Initialize lines container if available
        if cls._lines_class is not None:
            obj.lines = cls._lines_class()
        else:
            obj.lines = []

        return obj, tuple(remaining_args), kwargs

    def dopreinit(cls, obj, *args, **kwargs):
        """Clock setup and initial minimum period calculation."""
        obj, args, kwargs = super().dopreinit(obj, *args, **kwargs)

        # Set the clock to the first data feed
        if obj.datas:
            obj._clock = obj.datas[0]
        else:
            # No data feeds -- try to use the owner as the clock
            obj._clock = getattr(obj, "_owner", None)

        # Calculate initial minimum period from data feeds
        obj._minperiod = 1  # Default: at least one bar
        for d in obj.datas:
            dminperiod = getattr(d, "_minperiod", 1)
            if dminperiod > obj._minperiod:
                obj._minperiod = dminperiod

        # Propagate minperiod to all owned lines
        if hasattr(obj.lines, "__iter__"):
            for line in obj.lines:
                if hasattr(line, "updateminperiod"):
                    line.updateminperiod(obj._minperiod)

        return obj, args, kwargs

    def dopostinit(cls, obj, *args, **kwargs):
        """Period recalculation and owner registration."""
        obj, args, kwargs = super().dopostinit(obj, *args, **kwargs)

        # Recalculate minimum period from all children
        _periodrecalc(obj)

        # Auto-register with owner if found
        owner = getattr(obj, "_owner", None)
        if owner is not None and hasattr(owner, "addindicator"):
            owner.addindicator(obj)

        return obj, args, kwargs


def _is_line_root(obj):
    """Check whether *obj* is a line-aware object (LineRoot or similar).

    Avoids a hard import of LineRoot by checking for characteristic
    attributes.
    """
    try:
        from bucktrader.lineseries import LineRoot
        return isinstance(obj, LineRoot)
    except ImportError:
        # Fallback: duck-type check for line-like objects
        return hasattr(obj, "_minperiod") and hasattr(obj, "lines")


def _periodrecalc(obj):
    """Recalculate minimum period from children and owned lines.

    The minimum period is the maximum of:
    - The object's own lines' minimum periods
    - All child indicator minimum periods
    """
    minperiod = getattr(obj, "_minperiod", 1)

    # Check child indicators
    for child in obj._lineiterators.get(IndType, []):
        child_mp = getattr(child, "_minperiod", 1)
        if child_mp > minperiod:
            minperiod = child_mp

    # Check owned lines
    if hasattr(obj.lines, "__iter__"):
        for line in obj.lines:
            line_mp = getattr(line, "_minperiod", 1)
            if line_mp > minperiod:
                minperiod = line_mp

    obj._minperiod = minperiod


# ---------------------------------------------------------------------------
# SingletonMeta -- Ensures single instance per class
# ---------------------------------------------------------------------------

class SingletonMeta(MetaParams):
    """Metaclass ensuring only one instance exists per class.

    Used by Store classes to guarantee a single global instance.
    """

    def __call__(cls, *args, **kwargs):
        if not hasattr(cls, "_singleton") or cls._singleton is None:
            cls._singleton = super().__call__(*args, **kwargs)
        return cls._singleton


# ---------------------------------------------------------------------------
# Convenience base classes (using the metaclasses above)
# ---------------------------------------------------------------------------

class ComponentBase(metaclass=MetaBase):
    """Base class for all components. Uses MetaBase lifecycle."""
    pass


class ParamsBase(metaclass=MetaParams):
    """Base class for components with parameter support."""
    pass


class LineSeriesBase(metaclass=MetaLineSeries):
    """Base class for components with lines and params."""
    pass


class LineIteratorBase(metaclass=MetaLineIterator):
    """Base class for components with data discovery and auto-registration."""

    def addindicator(self, indicator):
        """Register a child indicator."""
        self._lineiterators[IndType].append(indicator)
        _periodrecalc(self)

    def addobserver(self, observer):
        """Register a child observer."""
        self._lineiterators[ObsType].append(observer)
        _periodrecalc(self)

    def addstrategy(self, strategy):
        """Register a child strategy."""
        self._lineiterators[StratType].append(strategy)


class SingletonBase(metaclass=SingletonMeta):
    """Base class for singleton stores."""
    pass
