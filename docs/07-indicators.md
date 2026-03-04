# Bucktrader Specification: Indicators

## 1. Concept

An indicator is a computation that transforms input lines (typically price data) into output lines (computed values). Indicators:

- Auto-register with their owning strategy
- Track their minimum period automatically
- Support both vectorized (`once`) and event-driven (`next`) computation
- Can be composed: indicators can use other indicators as inputs
- Support operator overloading for expressive definitions

## 2. Indicator Base

### 2.1 Class Hierarchy

```
LineIterator
└── DataAccessor
    └── IndicatorBase
        └── Indicator (primary base for all indicators)
```

### 2.2 Key Properties

| Property | Description |
|----------|-------------|
| `_ltype` | Set to `IndType` — identifies this as an indicator |
| `_mindatas` | Minimum data feeds required (default: 1) |
| `_nextforce` | If true, forces event-driven mode (no runonce) |

## 3. Defining an Indicator

### 3.1 Declaration

```
MyIndicator extends Indicator:
    lines = ("output1", "output2")             // Output lines
    params = [("period", 20)]                  // Parameters with defaults
    plotinfo = {subplot: true}                  // Plot configuration
    plotlines = {output1: {color: "blue"}}      // Per-line plot config
```

### 3.2 Computation Approaches

**Approach 1: Declarative (in constructor)**

Define output lines as expressions of input lines. The framework handles execution.

```
constructor():
    sma = SMA(data.close, period=p.period)
    lines.output1 = data.close - sma  // Creates a binding
```

When `lines.output1` is assigned a line expression, a binding is created. The expression automatically computes and propagates values during execution.

**Approach 2: Imperative (in next)**

Compute values bar-by-bar:

```
next():
    values = data.close.get(size=p.period)
    lines.output1[0] = sum(values) / p.period
```

**Approach 3: Vectorized (in once)**

Process all bars at once for performance:

```
once(start, end):
    src = data.close.array
    dst = lines.output1.array
    period = p.period
    for i in range(start, end):
        dst[i] = sum(src[i - period + 1 : i + 1]) / period
```

### 3.3 Automatic once() Generation

If an indicator defines `next()` but not `once()`, the framework generates a vectorized version by calling `next()` in a loop. This is done via `once_via_next()`.

Similarly, `preonce_via_prenext()` and `oncestart_via_nextstart()` provide automatic conversion.

## 4. Minimum Period

### 4.1 Automatic Calculation

The framework calculates minimum periods through the dependency chain:

1. Each data feed starts with `_minperiod = 1`
2. When an indicator is created with `period=20`, it adds 20 to its minperiod
3. When indicator A uses indicator B as input, A's minperiod includes B's minperiod
4. The strategy's minperiod is the max of all its indicators' minperiods

### 4.2 Period Chaining Example

```
SMA(close, period=20)              → minperiod = 20
EMA(SMA(close, 20), period=10)     → minperiod = 20 + 10 - 1 = 29
RSI(close, period=14)
  ├── UpDay(close)                 → minperiod = 2
  ├── SmoothedMA(UpDay, period=14) → minperiod = 2 + 14 - 1 = 15
  └── total                        → minperiod = 15
```

The `-1` comes from `LineSingle.addminperiod()` which accounts for the overlapping bar.

### 4.3 Manual Period Setting

```
constructor():
    addminperiod(p.period)  // Explicitly add to minimum period
```

## 5. Execution Lifecycle

### 5.1 Event-Driven Mode

```
For each bar:
    if bar_count < minperiod:
        prenext()       // Warmup: indicator data not yet valid
    elif bar_count == minperiod:
        nextstart()     // First valid bar (default: calls next())
    else:
        next()          // Main computation
```

### 5.2 Vectorized Mode

```
preonce(start=0, end=minperiod)                        // Warmup bars
oncestart(start=minperiod, end=minperiod+1)            // First valid bar
once(start=minperiod+1, end=total_bars)                // All remaining bars
```

### 5.3 Clock Advancement

In event-driven mode, indicators advance their clock before computing:

```
advance(size=1):
    if len(this) < len(this._clock):
        lines.forward(size=size)
```

This ensures the indicator's output line pointer advances in sync with its input data.

## 6. Built-in Indicator Categories

### 6.1 Basic Operations

Foundation indicators used by all others:

| Indicator | Description |
|-----------|-------------|
| `PeriodN` | Base for period-based indicators. Params: `period` |
| `OperationN` | Applies a function over a period. Params: `period`, `func` |
| `BaseApplyN` | Like OperationN with cleaner interface |
| `Highest` | Maximum value over period |
| `Lowest` | Minimum value over period |
| `ReduceN` | Reduce function over period |
| `AnyN` | Any value non-zero over period |
| `AllN` | All values non-zero over period |
| `SumN` | Sum over period |
| `Average` | Arithmetic mean over period |
| `ExponentialSmoothing` | EMA-style exponential smoothing |
| `ExponentialSmoothingDynamic` | EMA with dynamic alpha |
| `WeightedAverage` | Weighted average over period |
| `Accum` | Cumulative sum |
| `FindFirstIndex` / `FindLastIndex` | Find index of first/last occurrence |

### 6.2 Moving Averages

Base class: `MovingAverageBase` — provides `period` parameter and data input handling.

| Indicator | Aliases | Description |
|-----------|---------|-------------|
| `SimpleMovingAverage` | `SMA`, `MovAv.Simple` | Arithmetic mean over period |
| `ExponentialMovingAverage` | `EMA`, `MovAv.Exponential` | Exponentially weighted |
| `WeightedMovingAverage` | `WMA`, `MovAv.Weighted` | Linearly weighted |
| `SmoothedMovingAverage` | `SMMA`, `MovAv.Smoothed` | Modified EMA (Wilder's) |
| `AdaptiveMovingAverage` | `KAMA`, `MovAv.Adaptive` | Kaufman's adaptive |
| `DoubleExponentialMovingAverage` | `DEMA` | Double EMA (2*EMA - EMA(EMA)) |
| `TripleExponentialMovingAverage` | `TEMA` | Triple EMA |
| `ZeroLagExponentialMovingAverage` | `ZLEMA` | Zero-lag EMA |
| `HullMovingAverage` | `HMA` | Hull MA (weighted combination of WMAs) |
| `DicksonMovingAverage` | `DMA` | Dickson MA |

The `MovAv` class serves as a namespace for all moving average types.

### 6.3 Trend Indicators

| Indicator | Description |
|-----------|-------------|
| `MACD` | Moving Average Convergence/Divergence |
| `MACDHisto` | MACD with histogram |
| `ParabolicSAR` | Parabolic Stop and Reverse |
| `DirectionalMovement` | ADX, +DI, -DI |
| `DirectionalMovementIndex` | ADX, ADXR |
| `Aroon` | Aroon Up/Down |
| `AroonOscillator` | Aroon Up - Aroon Down |
| `Trix` | Triple EMA rate of change |
| `Ichimoku` | Ichimoku Kinko Hyo (5 lines) |

### 6.4 Oscillators

| Indicator | Description |
|-----------|-------------|
| `RSI` / `RelativeStrengthIndex` | Relative Strength Index |
| `Stochastic` | Stochastic %K and %D |
| `StochasticFull` | Full stochastic with smoothed %K |
| `WilliamsR` | Williams %R |
| `UltimateOscillator` | Multi-timeframe oscillator |
| `CommodityChannelIndex` / `CCI` | CCI |
| `MomentumOscillator` | Momentum |
| `RateOfChange` / `ROC` | Price rate of change |
| `DetrendedPriceOscillator` / `DPO` | Detrended Price Oscillator |
| `PercentagePriceOscillator` / `PPO` | Percentage Price Oscillator |

### 6.5 Volatility Indicators

| Indicator | Description |
|-----------|-------------|
| `BollingerBands` | Mean ± N standard deviations |
| `AverageTrueRange` / `ATR` | Average True Range |
| `TrueRange` | True Range (single bar) |
| `TrueHigh` / `TrueLow` | Gap-adjusted high/low |
| `StandardDeviation` / `StdDev` | Standard deviation over period |
| `MeanDeviation` | Mean absolute deviation |

### 6.6 Volume Indicators

| Indicator | Description |
|-----------|-------------|
| `OnBalanceVolume` / `OBV` | Cumulative volume based on price direction |
| `AccumDistIndex` | Accumulation/Distribution |
| `MoneyFlowIndicator` / `MFI` | Money Flow Index |
| `VolumeWeightedAveragePrice` / `VWAP` | Volume-weighted average price |

### 6.7 Other Indicators

| Indicator | Description |
|-----------|-------------|
| `PivotPoint` | Classic pivot points (P, R1, R2, R3, S1, S2, S3) |
| `HeikinAshi` | Heikin-Ashi transformed OHLC |
| `ZigZag` | ZigZag trend lines |
| `Envelope` | Price envelope (MA ± percentage) |
| `AwesomeOscillator` | Bill Williams' AO |
| `CrossOver` | Returns 1 on upward cross, -1 on downward cross |
| `CrossUp` / `CrossDown` | Individual cross signals |

## 7. Indicator Composition

### 7.1 Using Indicators as Inputs

Indicators can use other indicators as their data source:

```
sma = SMA(data.close, period=20)
bb = BollingerBands(sma, period=20)  // Bollinger of SMA
```

### 7.2 Arithmetic Composition

Lines support full operator overloading:

```
constructor():
    sma_fast = SMA(data, period=10)
    sma_slow = SMA(data, period=30)
    lines.spread = sma_fast - sma_slow          // Subtraction
    lines.ratio = sma_fast / sma_slow            // Division
    lines.signal = EMA(lines.spread, period=9)
```

### 7.3 Callable Indicators

Indicators can be called with different data to create new instances:

```
sma = SMA  // The class itself
sma_close = sma(data.close, period=20)
sma_volume = sma(data.volume, period=20)
```

### 7.4 Parameterized Moving Average

Many indicators accept a `movav` parameter to swap the underlying moving average:

```
BollingerBands extends Indicator:
    params = [
        ("period", 20),
        ("devfactor", 2.0),
        ("movav", MovAv.Simple),   // Swappable MA type
    ]

    constructor():
        ma = p.movav(data, period=p.period)
        ...
```

Users can pass any MovAv type: `BollingerBands(movav=EMA)`

## 8. Coupling Across Timeframes

When an indicator uses data from a different timeframe than its owner, a `LinesCoupler` is automatically inserted:

- The coupler holds the last value from the source line
- Only updates when the source line genuinely produces a new value
- Fills intermediate bars with the last known value

This allows mixing daily indicators in an intraday strategy seamlessly.

## 9. Plot Configuration

### 9.1 plotinfo

Controls how the indicator appears on charts:

```
plotinfo = {
    plot: true,              // Show on chart
    subplot: true,           // Separate subplot (false = overlay on data)
    plotname: "My Indicator", // Display name
    plotskip: false,         // Hide entirely
    plotabove: false,        // Position above data chart
    plothlines: [30, 70],    // Horizontal reference lines
    plotyticks: [],          // Y-axis tick marks
    plotymargin: 0.15,       // Y-axis margin
    plotmaster: null,        // Overlay on another component's subplot
}
```

### 9.2 plotlines

Controls per-line appearance:

```
plotlines = {
    sma: {
        color: "blue",
        linewidth: 1.5,
        linestyle: "--",      // Dashed
        _plotskip: false,
    },
    signal: {
        _plotskip: true,      // Hide this line
    },
    _fill_gt: ("sma", "signal", "green"),  // Fill when sma > signal
    _fill_lt: ("sma", "signal", "red"),    // Fill when sma < signal
}
```

Underscore-prefixed keys are directives, not line names.
