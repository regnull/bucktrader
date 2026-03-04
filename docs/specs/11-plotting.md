# Bucktrader Specification: Plotting System

## 1. Concept

The plotting system renders backtest results as multi-panel charts. Indicators, observers, and data feeds all contribute to the visual output through a unified configuration system.

## 2. Invocation

```
cortex.plot(plotter=null, numfigs=1, iplot=true, start=null,
            end=null, width=16, height=9, dpi=300, tight=true,
            use=null, **kwargs)
```

Cortex delegates to a `Plot` class that:

1. Creates a figure with subplots
2. For each data feed: plots OHLC/candlestick chart with volume overlay
3. For each indicator: plots in same subplot or separate based on `plotinfo`
4. For each observer: plots in separate subplot below data
5. Applies color scheme from `PlotScheme`

## 3. Chart Layout

```
┌─────────────────────────────────────────────┐
│  Data Chart (OHLC/Candle + Volume overlay)  │  ← rowsmajor weight
│  + Overlaid indicators (subplot=false)      │
├─────────────────────────────────────────────┤
│  Indicator Subplot 1                        │  ← rowsminor weight
├─────────────────────────────────────────────┤
│  Indicator Subplot 2                        │  ← rowsminor weight
├─────────────────────────────────────────────┤
│  Observer: Broker (Cash + Value)            │  ← rowsminor weight
├─────────────────────────────────────────────┤
│  Observer: Trades P&L                       │  ← rowsminor weight
└─────────────────────────────────────────────┘
```

## 4. PlotScheme

Controls the overall visual appearance of charts:

| Setting | Default | Description |
|---------|---------|-------------|
| `style` | `"line"` | Chart style: `"line"`, `"bar"`, `"candle"` |
| `volume` | `true` | Show volume |
| `voloverlay` | `true` | Overlay volume on price chart |
| `volscaling` | `0.33` | Volume height relative to price chart |
| `barup` / `bardown` | `"0.75"` / `"red"` | Bull/bear colors |
| `grid` | `true` | Show grid lines |
| `rowsmajor` | `5` | Weight for data charts |
| `rowsminor` | `1` | Weight for indicator/observer charts |
| `lcolors` | `tableau10` | Color palette for lines |
| `fillalpha` | `0.20` | Transparency for fill areas |

Additional scheme settings:
- Date formatting and tick rotation
- Legend position and transparency
- Major/minor chart proportions

## 5. Per-Component Plot Configuration

Each indicator, observer, or data feed controls its plotting via two class attributes: `plotinfo` and `plotlines`.

### 5.1 plotinfo

Controls how the component appears on charts:

```
plotinfo = {
    plot: true,              // Whether to plot
    subplot: true,           // Separate subplot (false = overlay on data)
    plotname: "",            // Display name
    plotskip: false,         // Skip entirely
    plotabove: false,        // Plot above data chart
    plotlinelabels: false,   // Show line labels
    plotlinevalues: true,    // Show line values
    plotvaluetags: true,     // Show value tags
    plotymargin: 0.0,        // Y-axis margin
    plotyhlines: [],         // Horizontal lines (y values)
    plotyticks: [],          // Y-axis tick marks
    plothlines: [],          // Horizontal reference lines
    plotforce: false,        // Force plotting even if hidden
    plotmaster: null,        // Master data for overlaying on another component's subplot
}
```

`plotinfo` is processed into a configuration subtype that inherits from parent classes, allowing subclasses to override individual settings.

### 5.2 plotlines

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
}
```

Underscore-prefixed keys are directives, not line names:

| Directive | Description |
|-----------|-------------|
| `_plotskip` | Hide this line from the chart |
| `_fill_gt` | Fill area when line1 > line2: `("line1", "line2", "color")` |
| `_fill_lt` | Fill area when line1 < line2: `("line1", "line2", "color")` |

### 5.3 Processing

During class creation, the component infrastructure (LineSeries):

1. Reads `plotinfo` and `plotlines` class attributes
2. Creates configuration subtypes that inherit from parent classes
3. Merges child overrides with parent defaults
4. Makes the configuration available as instance attributes

### 5.4 Example

```
RSI extends Indicator:
    plotinfo = {
        plot: true,
        subplot: true,
        plotname: "RSI",
        plothlines: [30, 70],
        plotymargin: 0.15,
    }

    plotlines = {
        rsi: {color: "purple", linewidth: 1.5},
        _fill_gt: (70, "red"),     // Fill above 70
        _fill_lt: (30, "green"),   // Fill below 30
    }
```

## 6. Class Aliases

Components can define alternative names for use in plot legends and lookups:

```
SimpleMovingAverage extends MovingAverageBase:
    alias = ("SMA", "MovingAverageSimple")
```

The component infrastructure registers these aliases so the indicator can be referenced by any name.
