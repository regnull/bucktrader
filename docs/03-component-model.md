# Bucktrader Specification: Component Model and Parameter System

## 1. Purpose

Bucktrader uses a component infrastructure to provide:

- **Declarative component definition**: Users declare lines and params as class-level attributes
- **Automatic lifecycle management**: Multi-phase initialization with hooks
- **Parameter inheritance**: Subclasses automatically inherit and can override parent params
- **Auto-registration**: Components register themselves with their parent (e.g., indicators with strategies)
- **Owner discovery**: Components find their parent by traversing the execution context

## 2. Component Infrastructure Hierarchy

```
Base (foundation)
└── Params (parameter support)
    └── LineSeries (line declaration and descriptor setup)
        └── LineIterator (data discovery, auto-registration)
            ├── Indicator
            ├── Observer
            └── Strategy
```

Additionally:
- **Singleton** (extends Params): For singleton stores
- **AnalyzerMeta** (extends Params): For analyzers (not part of line hierarchy)

## 3. Base — Foundation

### 3.1 Lifecycle Hooks

The base infrastructure defines a multi-phase object creation protocol. When a component is instantiated, the following methods are called in order:

```
Component.create(*args, **kwargs)
│
├── doprenew(*args, **kwargs)     → Can modify args/kwargs before creation
│
├── donew(*args, **kwargs)        → Object creation (allocation + field setup)
│   └── Returns (obj, args, kwargs)
│
├── dopreinit(obj, *args, **kwargs)  → Pre-init setup
│   └── Returns (obj, args, kwargs)
│
├── doinit(obj, *args, **kwargs)     → Calls constructor
│
└── dopostinit(obj, *args, **kwargs) → Post-init registration
    └── Returns (obj, args, kwargs)
```

Each hook receives the object being created and returns potentially modified `(obj, args, kwargs)`. Subclass infrastructure types override specific hooks to inject behavior.

### 3.2 Owner Discovery — `findowner`

A critical utility that traverses the execution context to find a parent object:

```
findowner(owned, cls, startlevel=2, skip=null)
```

- Walks up the call context examining local variables
- Finds the first object that is an instance of `cls`
- Used by indicators to find their owning strategy
- Used by strategies to find their owning Cortex
- `skip` parameter excludes specific objects from matching

This enables implicit parent-child relationships without explicit passing.

**Implementation note**: In languages without stack introspection, use explicit parent passing, thread-local storage, or context variables instead.

## 4. Params — Parameter System

### 4.1 Parameter Declaration

Parameters are declared as a list of `(name, default)` pairs:

```
MyIndicator extends Indicator:
    params = [
        ("period", 20),
        ("movav", SimpleMovingAverage),
        ("devfactor", 2.0),
    ]
```

### 4.2 Parameter Inheritance

When a class is created, the Params infrastructure:

1. Collects `params` from the new class definition
2. Creates a new configuration subtype that extends the parent's params
3. New params are appended; redefined params override parent defaults
4. The derived params type is stored on the new class

```
Base extends ParamsBase:
    params = [("period", 10)]

Derived extends Base:
    params = [("period", 20), ("factor", 2.0)]

// Derived.params has: period=20, factor=2.0
```

### 4.3 Parameter Access

Parameters are accessible via two attributes:

```
this.params.period    // Full name
this.p.period         // Shorthand alias (p == params)
```

The params object provides attribute access for each parameter.

### 4.4 AutoInfoClass

A dynamic type that stores key-value pairs as class-level defaults and allows instance-level override:

**Key Methods:**
- `getpairs()`: Returns all (name, default) pairs
- `getkeys()`: Returns just the parameter names
- `getdefaults()`: Returns just the default values
- `getitems()`: Returns pairs as an iterable
- `getvalues()`: Returns current values

**Instance Creation:**
When params are instantiated (during object creation), keyword arguments override defaults:

```
params_instance = ParamsClass(period=30)  // Override period, keep other defaults
```

### 4.5 Dependency Import

The Params infrastructure also handles automatic dependency imports via class attributes:

```
MyClass extends ParamsBase:
    packages = ["numpy"]                    // import numpy
    frompackages = [("math", ["sqrt"])]     // from math import sqrt
```

These dependencies are resolved during class creation and made available as class-level attributes.

## 5. LineSeries — Line Declaration

### 5.1 Processing Lines

When a class defines `lines = ("sma", "signal")`, the LineSeries infrastructure:

1. Calls `Lines.derive()` to create a new Lines container subtype
2. Adds `LineAlias` descriptors on the class for each line name
3. Supports aliases: `lines = [("sma", ("ma", "average")), "signal"]`
4. The first element in a tuple is the primary name; the rest are aliases

### 5.2 Processing Plot Info

Two special class attributes control plotting:

```
plotinfo = {
    plot: true,              // Whether to plot
    subplot: true,           // In separate subplot or overlaid
    plotname: "",            // Display name
    plotskip: false,         // Skip entirely
    plotabove: false,        // Plot above data
    plotlinelabels: false,
    plotlinevalues: true,
    plotvaluetags: true,
    plotymargin: 0.0,
    plotyhlines: [],         // Horizontal lines (y values)
    plotyticks: [],          // Y-axis tick marks
    plothlines: [],          // Horizontal reference lines
    plotforce: false,
    plotmaster: null,        // Master data for overlaying
}
```

```
plotlines = {
    sma: {color: "blue", linewidth: 2.0},
    signal: {_plotskip: true},    // underscore prefix = special directive
}
```

These are processed into configuration subtypes that inherit from parent classes.

### 5.3 Class Aliases

```
SimpleMovingAverage extends MovingAverageBase:
    alias = ("SMA", "MovingAverageSimple")
```

The LineSeries infrastructure registers these aliases so the indicator can be referenced by any name.

## 6. LineIterator — Auto-Registration

### 6.1 Data Discovery (donew)

During `donew`, the component infrastructure:

1. Scans `args` and `kwargs` for objects inheriting from `LineRoot`
2. Wraps raw line objects in `LineSeriesMaker` if needed
3. Stores discovered data in `obj.datas`
4. Creates convenience attributes:
   - `data` = `datas[0]`
   - `data0`, `data1`, etc.
   - `data_close`, `data0_high`, etc.
   - `dnames` = map of named data feeds

### 6.2 Clock Setup (dopreinit)

1. If no data feeds found, uses the owner as the clock
2. Sets `_clock` to the first data feed
3. Calculates initial `_minperiod` as the max of all data feed minperiods
4. Propagates minperiod to all owned lines

### 6.3 Registration (dopostinit)

1. Recalculates `_minperiod` from all lines and child indicators
2. Calls `_periodrecalc()` to propagate periods
3. Registers self with owner via `owner.addindicator(self)`

## 7. Indicator Infrastructure

Extends LineIterator with:

- **Object caching**: When `cortex.params.objcache=true`, identical indicators (same class + same args) are reused rather than recreated
- **Indicator class registry**: Maintains a global map of all indicator classes for lookup by name

## 8. Strategy Infrastructure

Extends LineIterator with:

- **Cortex discovery**: Finds the owning Cortex via `findowner`
- **Order/trade tracking**: Initializes `_orders`, `_trades` collections
- **Sizer setup**: Configures default position sizer
- **Environment setup**: Sets `env = cortex`, `broker = cortex.broker`

## 9. Singleton

Used by `Store` to ensure only one instance exists per store class:

```
Singleton extends Params:
    class_init():
        _singleton = null

    create(*args, **kwargs):
        if _singleton is null:
            _singleton = super.create(*args, **kwargs)
        return _singleton
```

## 10. Component Type Constants

LineIterator defines type constants used to classify components:

```
IndType = 0    // Indicator
StratType = 1  // Strategy
ObsType = 2    // Observer
```

These are used in the `_lineiterators` collection to organize children by type and control execution order.

## 11. Implementation Guidance

### 11.1 Recreating the Component System

To implement in any language:

1. **Parameter System**: Use a class-level registry of parameter definitions that supports inheritance and default overrides. Use decorators, code generation, builder patterns, or traits/interfaces depending on the language.

2. **Owner Discovery**: Either pass parent explicitly (simpler) or use thread-local storage / context variables.

3. **Auto-Registration**: Each component constructor should register itself with its parent. This can be done explicitly or via a factory/builder.

4. **Lifecycle Hooks**: Implement a multi-phase initialization protocol: create → pre-init → init → post-init.

5. **Line Declaration**: Use a declarative approach (attributes, annotations, or builder methods) to define output lines, then generate the backing storage.
