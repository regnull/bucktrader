# Bucktrader Specification: Project Overview and Architecture

## 1. Purpose

Bucktrader is an event-driven algorithmic trading framework designed for:

- **Backtesting** trading strategies against historical data
- **Paper trading** with simulated order execution
- **Live trading** against real brokers (Interactive Brokers, OANDA)
- **Strategy optimization** via parameter sweeps with parallel execution support

The framework provides a unified programming model across all modes — the same strategy code runs unchanged in backtesting, paper, and live environments.

## 2. Core Design Principles

### 2.1 Everything is a Line

The central abstraction is the **Line** — a time-indexed series of floating-point values. Prices, indicator outputs, datetime values, volume, and even boolean signals are all represented as Lines. This unified model enables:

- Consistent indexing: `line[0]` is always the current value, `line[-1]` is the previous value
- Composability: Lines can be combined with arithmetic operators to create new Lines
- Automatic dependency tracking: The framework knows when each Line has enough data to be valid

### 2.2 Declarative Component Definition

Components (strategies, indicators, data feeds) are defined by declaring:

- **Lines** they produce (output time series)
- **Parameters** they accept (configurable values with defaults)
- **Computation logic** (how outputs derive from inputs)

The framework infrastructure handles wiring, registration, and lifecycle management automatically.

### 2.3 Dual Execution Modes

Every computation supports two execution modes:

- **Vectorized (runonce)**: Process all historical bars at once — fastest for backtesting
- **Event-driven (next)**: Process one bar at a time — required for live trading

### 2.4 Automatic Period Management

Each Line tracks its **minimum period** — the number of bars needed before valid values can be produced. A 20-period SMA needs 20 bars. An RSI(14) built on an SMA(20) needs 33 bars (20 + 14 - 1). The framework computes these automatically and calls the appropriate lifecycle hooks.

## 3. Architecture Overview

### 3.1 Component Hierarchy

```
Cortex (Engine/Orchestrator)
├── Data Feeds (market data sources)
│   ├── Filters (data transformations: resampling, replay, Renko, etc.)
│   └── Lines: datetime, open, high, low, close, volume, openinterest
├── Broker (order execution and portfolio management)
│   ├── Commission Schemes
│   ├── Position Tracking
│   └── Fill Simulation / Slippage
├── Strategies (user-defined trading logic)
│   ├── Indicators (technical analysis computations)
│   │   └── Sub-indicators (indicators built on indicators)
│   ├── Observers (real-time monitoring/visualization)
│   │   └── Child Analyzers
│   ├── Analyzers (performance metrics collection)
│   ├── Sizers (position sizing logic)
│   └── Timers (scheduled callbacks)
└── Writers (output formatting)
```

### 3.2 Class Hierarchy

```
MetaBase (component infrastructure)
└── MetaParams (parameter inheritance)
    └── MetaLineSeries (line declaration and descriptor setup)
        └── MetaLineIterator (data discovery, auto-registration)
            ├── LineIterator
            │   ├── DataAccessor
            │   │   ├── IndicatorBase → Indicator
            │   │   ├── ObserverBase → Observer
            │   │   └── StrategyBase → Strategy
            │   └── AbstractDataBase (data feeds)
            └── MetaStrategy (strategy-specific setup)

MetaParams (standalone usage)
├── BrokerBase → BackBroker
├── CommInfoBase
├── SizerBase
├── Store (singleton)
└── Cortex
```

### 3.3 Data Flow

```
Data Source → DataFeed.load() → Filters → LineBuffer storage
                                              ↓
                                    Indicator computation
                                              ↓
                                    Strategy.next() (user logic)
                                              ↓
                                    Order submission → Broker
                                              ↓
                                    Broker.next() → Order execution
                                              ↓
                                    Notifications → Strategy callbacks
                                              ↓
                                    Observers record / Analyzers collect
```

## 4. Execution Flow

### 4.1 Setup Phase

1. User creates a `Cortex` instance
2. Data feeds are added via `adddata()`, `resampledata()`, or `replaydata()`
3. Strategies are registered via `addstrategy()` or `optstrategy()`
4. Optional: add custom brokers, analyzers, observers, sizers, writers

### 4.2 Initialization Phase (inside `cortex.run()`)

1. Data feeds are started and optionally preloaded into memory
2. Strategy instances are created
3. During strategy construction, indicators are instantiated
4. Indicators auto-register with their parent strategy
5. Minimum periods are calculated by propagating through the dependency graph
6. Observers and analyzers are attached

### 4.3 Main Loop

Two execution paths depending on configuration:

**Vectorized Path** (`preload=True, runonce=True`):
1. All data is preloaded into memory
2. Indicators compute all values at once via `once()` methods
3. Strategy iterates bar-by-bar via `next()` calls
4. Broker processes orders after each bar

**Event-Driven Path** (`preload=False` or live mode):
1. Data feeds produce one bar at a time
2. Bars are synchronized across multiple feeds by datetime
3. Indicators compute incrementally via `next()` methods
4. Strategy `next()` is called
5. Broker processes orders

### 4.4 Bar Processing Order (per bar)

1. Data feeds advance (new bar loaded)
2. Multi-feed datetime synchronization
3. Cheat-on-open timers fire (optional)
4. Broker notifications delivered to strategy
5. Indicators update
6. Strategy `prenext()` / `nextstart()` / `next()` called
7. Regular timers fire
8. Observers and analyzers update

### 4.5 Teardown Phase

1. `strategy.stop()` called
2. Analyzers finalize calculations
3. Results returned to user

## 5. Key Abstractions Summary

| Abstraction | Purpose | Spec Document |
|------------|---------|---------------|
| Lines System | Time-indexed data representation | [02-lines-system.md](02-lines-system.md) |
| Component Infrastructure | Declarative component definition | [03-component-model.md](03-component-model.md) |
| Cortex | Engine orchestration | [04-cortex.md](04-cortex.md) |
| Data Feeds | Market data ingestion | [05-data-feeds.md](05-data-feeds.md) |
| Strategies | User trading logic | [06-strategies.md](06-strategies.md) |
| Indicators | Technical analysis | [07-indicators.md](07-indicators.md) |
| Broker System | Order execution and portfolio | [08-broker.md](08-broker.md) |
| Analyzers & Observers | Metrics and monitoring | [09-analyzers-observers.md](09-analyzers-observers.md) |
| Live Trading | Real-time broker integration | [10-live-trading.md](10-live-trading.md) |

## 6. Memory Management Modes

The framework supports multiple memory strategies controlled by `cortex.params.exactbars`:

| Mode | Value | Description |
|------|-------|-------------|
| Unbounded | `False` (0) | All data kept in memory. Fastest. Supports plotting. |
| Save Memory Level 1 | `1` | Sub-indicators and operations use fixed-size buffers. Plotting and preloading still work. Runonce disabled. |
| Save Memory Level 0 | `-1` | All lines use fixed-size buffers equal to their minimum period. No plotting. |
| Minimum Memory | `-2` | Absolute minimum buffers. No plotting. |

## 7. Optimization Support

Cortex supports parameter optimization for strategies:

1. User registers strategy with `optstrategy(StratClass, param1=[v1, v2], param2=[v3, v4])`
2. Cortex generates the cartesian product of parameter combinations
3. Each combination runs as an independent backtest
4. Parallel processing distributes work across CPU cores
5. Results can be lightweight (`optreturn=True`) to save memory — only params and analyzer results returned
6. Data can be preloaded once and shared (`optdatas=True`) for ~20% speedup
