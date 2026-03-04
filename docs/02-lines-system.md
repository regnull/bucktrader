# Bucktrader Specification: The Lines System

## 1. Concept

The **Lines System** is the foundational data model. A "line" is a time-indexed array of `float64` values representing any time series — prices, indicator outputs, datetime values, boolean signals, or arbitrary numeric data.

The key insight: index `0` always refers to the **current bar**. There is no need to pass around an index variable. Negative indices look into the past; positive indices look into the future (when available, e.g., during preloading).

```
Past ←————————————————————→ Future
... line[-3] line[-2] line[-1] line[0] line[1] line[2] ...
                               ↑
                         Current bar
```

Note: The indexing convention uses **negative** indices for past values when accessed from user code (e.g., `data.close[-1]` for yesterday's close). Internally, the buffer uses positive offsets from the current position.

## 2. Class Hierarchy

```
LineRoot (abstract base)
├── LineSingle (single line — base for LineBuffer)
│   └── LineBuffer (actual storage implementation)
│       └── LineActions (buffer + auto-registration + min period)
│           ├── LinesOperation (binary operations: line OP line)
│           ├── LineOwnOperation (unary operations: OP(line))
│           ├── LineDelay (time-shifted access: line(-N))
│           └── LineForward (future access: line(N))
└── LineMultiple (container for multiple lines)
    └── LineSeries (named lines with descriptors)
        └── LineIterator (iteration and children management)
```

## 3. LineBuffer — Core Storage

### 3.1 Storage Modes

LineBuffer supports two storage modes:

| Mode | Implementation | Use Case |
|------|----------------|----------|
| **Unbounded** | Growable array of `float64` | Default. Grows without limit. Supports full history access and plotting. |
| **QBuffer** | Fixed-size circular buffer (`maxlen=N`) | Memory-saving mode. Only the last N values are kept. |

### 3.2 Key Properties

- **`idx`**: The logical index pointing to the current (index 0) position in the underlying array. Starts at -1 (no data). Advances as bars are processed.
- **`lencount`**: Number of bars that have been produced. Used by `len(line)`.
- **`extension`**: Number of future positions that have been allocated (for lookahead).
- **`array`**: The underlying storage (growable array or circular buffer).
- **`bindings`**: List of other LineBuffers that receive values whenever this buffer is written to.

### 3.3 Operations

| Operation | Description |
|-----------|-------------|
| `forward(value=NaN, size=1)` | Move pointer forward by `size` positions. Append `value` to the array. Propagate to all bindings. In QBuffer mode, old values are automatically discarded. |
| `backwards(size=1, force=false)` | Move pointer backward, removing the last `size` values. Used for replay operations. |
| `rewind(size=1)` | Move pointer backward without removing values (logical only). |
| `advance(size=1)` | Move pointer forward without appending values (logical only). |
| `extend(size=0)` | Allocate future positions by appending NaN values. |
| `home()` | Reset the pointer to the beginning of the data. |
| `reset()` | Clear all data and reset indices to initial state. |
| `get(ago=0, size=1)` | Return a slice of values: `size` values ending at position `ago` relative to current. |
| `getzero(idx=0, size=1)` | Return a slice of values using absolute index (not relative to current). |

### 3.4 Indexing

```
line[0]    // Current value (most recent bar)
line[-1]   // Previous bar's value
line[-N]   // N bars ago
line[1]    // Next bar (future, requires extend())
```

Internally, `get(index)` and `set(index, value)` translate to: `array[idx + ago]`

### 3.5 Bindings

When a LineBuffer has bindings, setting a value at index 0 also sets that value in all bound buffers:

```
set(index, value):
    array[idx + index] = value
    for each binding in bindings:
        binding.set(index, value)
```

This enables indicator outputs to be directly connected to other lines.

### 3.6 QBuffer Mode (Memory Saving)

When `qbuffer(savemem, extrasize)` is called:
- Storage switches to a circular buffer with `maxlen = minperiod + extrasize`
- The `idx` pointer is clamped to prevent exceeding the buffer boundary
- Old values outside the window are automatically discarded
- `extrasize` is needed for resampling/replay which requires backwards movement

## 4. LineRoot — Abstract Base

LineRoot defines the interface that all line objects must support:

### 4.1 Period Management

| Method | Description |
|--------|-------------|
| `setminperiod(minperiod)` | Set the minimum period (absolute). |
| `updateminperiod(minperiod)` | Update minimum period only if the new value is larger. |
| `addminperiod(minperiod)` | Add to the current minimum period (cumulative). |
| `incminperiod(minperiod)` | Increment minimum period (no -1 adjustment, unlike addminperiod on LineSingle). |

The `_minperiod` attribute tracks how many bars must be available before this line produces valid output.

### 4.2 Iteration Interface

Each line object supports these lifecycle callbacks:

```
prenext()     — Called when current bar < minperiod (warmup)
nextstart()   — Called exactly once when bar == minperiod (first valid bar)
next()        — Called for each subsequent bar

preonce(start, end)    — Vectorized warmup
oncestart(start, end)  — Vectorized first valid range
once(start, end)       — Vectorized main computation
```

### 4.3 Two-Stage System

Lines operate in two stages:

| Stage | When | Behavior |
|-------|------|----------|
| **Stage 1** (Init) | During construction | Arithmetic operations create **operation objects** (lazy). Comparisons create LineOperation objects. |
| **Stage 2** (Execution) | During `next()/once()` | Comparisons return **boolean values** directly. Used in strategy logic like `if data.close[0] > sma[0]`. |

`_stage1()` and `_stage2()` are called on all line objects to switch modes. This enables declarative indicator definitions during construction while allowing imperative boolean tests in `next()`.

### 4.4 Operator Overloading

LineRoot overloads all arithmetic and comparison operators:

**Arithmetic**: `+`, `-`, `*`, `/`, `//`, `%`, `**`, `-` (neg), `+` (pos), `abs()`

**Comparison**: `<`, `<=`, `>`, `>=`, `==`, `!=`

**Logical**: `&` (and), `|` (or), `^` (xor)

In Stage 1, these create `LinesOperation` or `LineOwnOperation` objects. In Stage 2, comparisons evaluate immediately to booleans.

## 5. LineSingle and LineMultiple

### 5.1 LineSingle

Base for objects that represent a **single** line (one time series). Adds special handling for `addminperiod` — subtracts 1 because the overlapping bar is already counted.

### 5.2 LineMultiple

Base for objects that contain **multiple** lines. Operations on a LineMultiple are delegated to its first (default) line. Stage changes and minperiod updates propagate to all contained lines.

## 6. Lines Container

The `Lines` class is a container that holds multiple `LineBuffer` instances. It is dynamically subclassed for each component type.

### 6.1 Derivation

```
// The derive() method creates a new Lines subclass:
NewLines = Lines.derive('MyIndicator',
    lines=('sma', 'signal'),  // line names
    extralines=0,              // anonymous extra lines
    otherbases=())             // lines from other bases
```

This creates:
- A new type with `getlines()` returning all line names
- Descriptor attributes for named access: `lines.sma`, `lines.signal`
- Each line backed by its own `LineBuffer`

### 6.2 Line Aliases

Named access uses `LineAlias` descriptors:

```
LineAlias:
    constructor(line_index):
        this.line = line_index

    get(obj):
        return obj.lines[this.line]

    set(obj, value):
        // If value is a LineMultiple, take its first line
        // Add binding from value to the target line
        value.addbinding(obj.lines[this.line])
```

Setting a line alias creates a **binding** — when the source line updates, the target line receives the same value.

## 7. LineSeries

Extends `Lines` with metadata:

- **plotinfo**: Plot configuration (subplot, colors, visibility, margins)
- **plotlines**: Per-line plot configuration (style, width, color)
- **Class aliases**: Alternative names for the class

### 7.1 MetaLineSeries

The component infrastructure that processes class definitions:

1. Reads the `lines` class attribute (tuple of line names)
2. Calls `Lines.derive()` to create a Lines container subtype
3. Sets up `LineAlias` descriptors on the class for each line
4. Processes `plotinfo` and `plotlines` as configuration subtypes
5. Creates aliases for alternative class names

## 8. LineIterator

LineIterator adds iteration capability and child management on top of LineSeries. It is the bridge between the lines data model and the component lifecycle.

For the full LineIterator specification — including data discovery, child management, period recalculation, and iteration methods — see [03-component-model.md, Section 6](03-component-model.md).

## 9. Line Operations

### 9.1 LinesOperation (Binary)

Represents `line1 OP line2` or `line OP scalar`:

```
LinesOperation:
    constructor(a, b, operation):
        // a: first operand (line)
        // b: second operand (line or scalar)
        // operation: function (e.g., add)

    next():
        this[0] = operation(a[0], b[0])

    once(start, end):
        for i in range(start, end):
            dst[i] = op(srca[i], srcb[i])
```

### 9.2 LineDelay

Access a line's value from N bars ago:

```
delayed = line(-3)  // Creates LineDelay referencing 3 bars back
// delayed[0] == line[-3]  (at any point in time)
```

Implemented by reading from offset position in source array.

### 9.3 LineForward

Access a line's future value (requires data to be preloaded):

```
future = line(2)   // Creates LineForward referencing 2 bars ahead
```

## 10. Lines Coupler

When using data feeds or indicators with **different timeframes**, a `LinesCoupler` adapts lines to the strategy's clock:

- Stores the latest value from the source line
- Only updates when the source line has genuinely new data
- Fills intermediate bars with the last known value

This enables mixing daily and weekly indicators in the same strategy seamlessly.

## 11. DateTime Line

Every data feed has a special `datetime` line that stores timestamps as `float64` values using a days-since-epoch encoding (floating point). Utility functions convert between:

- `date2num(datetime)` → float
- `num2date(float)` → datetime
- `time2num(time)` → float (fractional day)

The datetime line serves as the **clock** for synchronization across multiple data feeds and timeframes.
