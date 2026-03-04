# Bucktrader Specification: Analyzers, Observers, and Writers

## 1. Analyzers

### 1.1 Concept

Analyzers collect performance metrics during a backtest. Unlike indicators, they:

- Do **not** produce lines (no time-series output)
- Store results in an ordered map via `rets`
- Are called for each bar but accumulate statistics
- Support nesting (child analyzers)
- Have access to `strategy`, `data`, `datas`

### 1.2 Analyzer Interface

```
MyAnalyzer extends Analyzer:
    start():
        // Called once before backtesting starts

    prenext():
        // Called during warmup bars

    next():
        // Called for each bar after warmup

    stop():
        // Called once after backtesting ends
        // Finalize calculations here

    notify_order(order):
        // Called when an order status changes

    notify_trade(trade):
        // Called when a trade opens/closes

    notify_cashvalue(cash, value):
        // Called with portfolio updates

    notify_fund(cash, value, fundvalue, shares):
        // Called with fund-mode updates

    get_analysis():
        // Return the results map
        return rets
```

### 1.3 Results Storage

Analyzers use `rets` — an auto-ordered map that supports dot-notation access and auto-creates nested maps:

```
stop():
    rets.total_return = (final_value / initial_value) - 1.0
    rets.max_drawdown = max_dd
    rets.trades.total = trade_count
    rets.trades.won = wins
```

### 1.4 TimeFrame Analyzers

`TimeFrameAnalyzerBase` extends Analyzer to support time-period aggregation:

- Params: `timeframe`, `compression`
- Tracks when time periods change (day, week, month, year)
- Calls `on_dt_over()` at period boundaries
- Maintains `dtkey` (current period's datetime key)
- Stores results keyed by datetime

### 1.5 Built-in Analyzers

| Analyzer | Description |
|----------|-------------|
| **TradeAnalyzer** | Comprehensive trade statistics: total trades, won/lost, streak analysis, P&L distribution |
| **SharpeRatio** | Sharpe ratio: `(mean_return - risk_free) / std_return` over configurable timeframe |
| **SharpeRatio_A** | Annualized Sharpe ratio |
| **Returns** | Total, average, and compound returns |
| **AnnualReturn** | Year-by-year returns |
| **TimeReturn** | Period-by-period returns (daily, weekly, monthly, etc.) |
| **DrawDown** | Maximum drawdown: depth, length, money lost |
| **Calmar** | Calmar ratio: `annualized_return / max_drawdown` |
| **SQN** | System Quality Number: `sqrt(N) * mean_pnl / std_pnl` |
| **VWR** | Variability-Weighted Return (risk-adjusted) |
| **LogReturnsRolling** | Rolling log returns |
| **PeriodStats** | Per-period statistics (average, stddev, positive/negative days) |
| **Transactions** | Log of all transactions (datetime, size, price, value) |
| **PositionsValue** | Portfolio position values over time |
| **GrossLeverage** | Portfolio leverage over time |

### 1.6 TradeAnalyzer Details

The most comprehensive built-in analyzer. Tracks:

```
total:
    total: int            // Total trades
    open: int             // Currently open
    closed: int           // Completed
long:
    total, won, lost: int
short:
    total, won, lost: int
streak:
    won.current, won.longest: int
    lost.current, lost.longest: int
pnl:
    gross.total, gross.average: float
    net.total, net.average: float
won:
    total: int
    pnl.total, pnl.average, pnl.max: float
lost:
    total: int
    pnl.total, pnl.average, pnl.max: float
len:
    total, average, max, min: int  // Trade duration in bars
    won.total, won.average, won.max, won.min: int
    lost.total, lost.average, lost.max, lost.min: int
```

### 1.7 SharpeRatio Details

Parameters:
| Parameter | Default | Description |
|-----------|---------|-------------|
| `timeframe` | `Years` | Annualization timeframe |
| `compression` | `1` | Timeframe compression |
| `riskfreerate` | `0.01` | Annual risk-free rate |
| `convertrate` | `true` | Convert annual rate to per-period |
| `factor` | `null` | Custom annualization factor |
| `annualize` | `true` | Annualize the ratio |
| `fund` | `null` | Use fund-mode values |

### 1.8 Accessing Analyzer Results

```
results = cortex.run()
strat = results[0]

// Access specific analyzer
sharpe = strat.analyzers.sharperatio.get_analysis()
trades = strat.analyzers.tradeanalyzer.get_analysis()

// Print results
strat.analyzers.sharperatio.print()
```

## 2. Observers

### 2.1 Concept

Observers are special indicators that:

- Produce **lines** (time-series output) for visualization
- Auto-plot on charts
- Track strategy/broker state each bar
- Can contain child analyzers
- Always run in event-driven mode (never runonce)
- Call `prenext()` and `next()` (not skipping warmup, using `_nextforce=true`)

### 2.2 Observer vs. Analyzer

| Aspect | Analyzer | Observer |
|--------|----------|----------|
| Output | Map of results | Lines (time series) |
| Plotting | No | Yes |
| Execution | Event-driven | Event-driven (forced) |
| Warmup | Follows minperiod | Runs from bar 1 |
| Purpose | Statistics | Real-time visualization |

### 2.3 Observer Interface

Observers are defined like indicators:

```
MyObserver extends Observer:
    lines = ("value", "cash")

    next():
        lines.value[0] = strategy.broker.getvalue()
        lines.cash[0] = strategy.broker.getcash()
```

### 2.4 Built-in Observers

| Observer | Lines | Description |
|----------|-------|-------------|
| **Broker** | `cash`, `value` | Portfolio cash and total value |
| **BuySell** | `buy`, `sell` | Buy/sell signal markers on price chart |
| **Trades** | `pnlplus`, `pnlminus` | Trade P&L markers (green for profit, red for loss) |
| **DrawDown** | `drawdown`, `maxdrawdown` | Current and max drawdown |
| **TimeReturn** | `timereturn` | Period returns (wraps TimeReturn analyzer) |
| **LogReturns** | `logreturns` | Log returns (wraps LogReturnsRolling analyzer) |
| **FundValue** | `fundvalue` | Fund NAV per share |
| **FundShares** | `fundshares` | Total fund shares |
| **Benchmark** | `bench` | Benchmark comparison (uses TimeReturn analyzer) |

### 2.5 Standard Stats (stdstats)

When `cortex.params.stdstats=true` (default), these observers are auto-added:

1. **Broker** (cash + value)
2. **BuySell** (trade markers on chart)
3. **Trades** (P&L markers)

### 2.6 Observer with Child Analyzer

Observers can instantiate analyzers that update alongside them:

```
Benchmark extends Observer:
    lines = ("bench",)
    params = [("data", null), ("timeframe", null)]

    constructor():
        // Create a child analyzer
        _tr = TimeReturn(data=p.data, timeframe=p.timeframe)

    next():
        lines.bench[0] = _tr.rets.get(key, 0.0)
```

### 2.7 Per-Data Observers

When added with `cortex.addobservermulti(ObsClass)` or `per_data=true`, one observer instance is created for each data feed. Useful for tracking metrics per instrument.

## 3. Writers

### 3.1 Concept

Writers output strategy data (prices, indicators, observers, analyzers) to files or stdout in a structured format.

### 3.2 Writer Interface

```
MyWriter:
    start():
        // Open output file/stream

    stop():
        // Close output file/stream

    addheaders(headers):
        // Receive column headers

    next():
        // Called each bar — write current values
```

### 3.3 WriterFile (Built-in)

The default writer that outputs CSV-formatted data.

**Parameters:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `out` | `stdout` | Output file/stream |
| `close_out` | `false` | Close the output when done |
| `csv` | `true` | Enable CSV value output |
| `csvsep` | `,` | CSV separator |
| `csv_filternan` | `true` | Replace NaN with empty string |
| `csv_counter` | `true` | Include bar counter column |
| `indent` | `2` | Indentation for section headers |
| `separators` | `true` | Add separator lines between sections |
| `rounding` | `null` | Decimal places for rounding |

### 3.4 Writer Output Structure

```
========================================
Strategy: MyStrategy
    params: period=20, factor=2.0
----------------------------------------
Data Feeds:
    - data0: AAPL (TimeFrame.Days)
    - data1: MSFT (TimeFrame.Days)
Indicators:
    - SMA(period=20)
    - BollingerBands(period=20, devfactor=2.0)
Observers:
    - Broker
    - BuySell
Analyzers:
    - SharpeRatio: 1.45
    - TradeAnalyzer: {total: 15, won: 9, lost: 6, ...}
========================================
```

When CSV is enabled, each bar outputs a row with all data feed values, indicator values, and observer values.

## 4. Plotting System

### 4.1 Concept

The plotting system renders backtest results as multi-panel charts.

### 4.2 Chart Layout

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

### 4.3 PlotScheme

Controls visual appearance:

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

### 4.4 Plot Configuration Per Component

Each indicator/observer controls its plotting via `plotinfo` and `plotlines`:

```
plotinfo = {
    plot: true,              // Whether to plot
    subplot: true,           // Separate subplot vs overlay
    plotname: "RSI",         // Display name
    plotabove: false,        // Position above data
    plothlines: [30, 70],    // Horizontal reference lines
    plotmaster: null,        // Overlay on another component
}

plotlines = {
    rsi: {color: "purple", linewidth: 1.5},
    _fill_gt: (70, "red"),     // Fill above 70
    _fill_lt: (30, "green"),   // Fill below 30
}
```

### 4.5 Invocation

```
cortex.plot(
    style="candle",          // Override default style
    numfigs=1,               // Number of figures
    iplot=true,              // Interactive (notebook)
    start=datetime(...),     // Plot start date
    end=datetime(...),       // Plot end date
    width=16, height=9,      // Figure dimensions
    dpi=300,                 // Resolution
)
```
