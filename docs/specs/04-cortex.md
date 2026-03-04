# Bucktrader Specification: Cortex (Engine Orchestrator)

## 1. Purpose

Cortex is the top-level orchestrator. It:

- Manages the registry of data feeds, strategies, brokers, observers, analyzers, and writers
- Controls execution mode (preload, runonce, live, optimization)
- Implements the main event loop
- Synchronizes multiple data feeds
- Manages timers
- Coordinates optimization runs

## 2. Configuration Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `preload` | `true` | Load all data into memory before running strategies |
| `runonce` | `true` | Run indicators in vectorized mode (requires preload) |
| `live` | `false` | Force live-trading mode (disables preload and runonce) |
| `maxcpus` | `null` | Max CPU cores for optimization (null = all) |
| `stdstats` | `true` | Add default observers (Broker, Trades, BuySell) |
| `exactbars` | `false` | Memory saving level (false/0, 1, -1, -2) |
| `optdatas` | `true` | Preload data once for all optimization runs |
| `optreturn` | `true` | Return lightweight results during optimization |
| `objcache` | `false` | Cache identical indicator objects |
| `writer` | `false` | Add default WriterFile (stdout) |
| `tradehistory` | `false` | Log trade history events |
| `oldsync` | `false` | Use old data synchronization (data0 as master) |
| `tz` | `null` | Global timezone for strategies |
| `cheat_on_open` | `false` | Call `next_open()` before broker processes orders |
| `broker_coo` | `true` | Auto-configure broker for cheat-on-open |
| `quicknotify` | `false` | Deliver broker notifications immediately |

## 3. Registry Methods

### 3.1 Data Feeds

```
adddata(data, name=null)
    Register a data feed. Optionally assign a name.
    If the data reports itself as live, Cortex switches to live mode.

resampledata(data, timeframe, compression, **kwargs)
    Add data with a Resampler filter attached.
    Resampler aggregates bars into larger timeframes.

replaydata(data, timeframe, compression, **kwargs)
    Add data with a Replayer filter attached.
    Replayer delivers intermediate (incomplete) bars as they build.

chaindata(*datas, name=null)
    Chain multiple data feeds end-to-end (e.g., contract1 then contract2).

rolloverdata(*datas, name=null, **kwargs)
    Create a rollover feed that switches between data feeds based on
    configurable rollover conditions (e.g., futures contract expiration).
```

### 3.2 Strategies

```
addstrategy(strategy_class, *args, **kwargs)
    Register a strategy class with fixed parameters.
    Multiple strategies can be added; each runs independently.

optstrategy(strategy_class, *args, **kwargs)
    Register a strategy for parameter optimization.
    Keyword arguments with list values define the parameter grid.
    Cortex generates the cartesian product of all parameter combinations.
```

### 3.3 Components

```
addindicator(indicator_class, *args, **kwargs)
    Add an indicator to ALL strategies (applied during setup).

addobserver(observer_class, *args, **kwargs)
    Add an observer to all strategies. If per_data=true, one instance per data feed.

addobservermulti(observer_class, *args, **kwargs)
    Shorthand for addobserver with per_data=true.

addanalyzer(analyzer_class, *args, **kwargs)
    Add a performance analyzer to all strategies.

addsizer(sizer_class, *args, **kwargs)
    Set the default position sizer for all strategies.

addsizer_byidx(idx, sizer_class, *args, **kwargs)
    Set a sizer for a specific strategy by index.

addwriter(writer_class, *args, **kwargs)
    Add an output writer.

addcalendar(calendar)
    Set a trading calendar. Accepts:
    - TradingCalendarBase subtype instance
    - String (exchange name for market calendar lookup)
    - Market calendar instance

add_timer(when, offset=0, repeat=0, weekdays=[],
          weekcarry=true, monthdays=[], monthcarry=true,
          allow=null, tzdata=null, strats=false, cheat=false,
          *args, **kwargs)
    Schedule a recurring timer callback.
```

### 3.4 Broker

```
setbroker(broker)
    Replace the default broker with a custom one.

getbroker()
    Return the current broker.

broker (property)
    Get/set the broker.
```

The default broker is `BackBroker` (backtesting broker) with 10,000 initial cash.

## 4. Execution

### 4.1 `run(**kwargs)`

The main entry point. Returns a list of strategy instances (or `OptReturn` objects during optimization).

**Flow:**

1. Apply any runtime parameter overrides from `kwargs`
2. Determine execution mode based on data feed capabilities and parameters
3. If optimization is requested:
   a. Generate parameter combinations (cartesian product)
   b. If `maxcpus` > 1: use parallel processing to run combinations concurrently
   c. Else: run combinations sequentially
4. For each parameter combination (or single run):
   a. Call `runstrategies(iterstrat)`
5. Return results

### 4.2 `runstrategies(iterstrat, predata=false)`

Sets up and runs strategies for one parameter combination.

**Flow:**

1. Initialize broker, data feeds, and stores
2. If `preload` and data can preload: load all data into memory
3. For each registered strategy class:
   a. Instantiate with given parameters
   b. Add indicators registered via `addindicator`
   c. Add observers (stdstats if enabled, plus custom)
   d. Add analyzers
   e. Add writers
   f. Set sizer
4. Switch all components to Stage 2 (execution mode)
5. Choose execution path:
   - If `runonce` and preloaded: call `_runonce(runstrats)`
   - Else: call `_runnext(runstrats)`
6. Call `strategy.stop()` for each strategy
7. If `optreturn`: wrap results in lightweight `OptReturn`

### 4.3 `_runonce(runstrats)` — Vectorized Execution

```
For each strategy:
    strategy._once()  // Compute all indicators vectorized

For each bar (0 to total bars):
    Find minimum datetime across all data feeds
    For each data feed with matching datetime:
        Advance the data feed pointer

    Check cheat-on-open timers
    Process broker notifications → deliver to strategies

    For each strategy:
        strategy._oncepost(dt)  // Evaluate prenext/next for this bar

    Check regular timers
```

### 4.4 `_runnext(runstrats)` — Event-Driven Execution

```
Loop:
    Notify stores of new tick

    For each data feed:
        ret = data.next()  // Load next bar
        If data reports as live: enable live mode

    If no data produced a bar: break (end of data)

    Synchronize data feeds:
        Find minimum datetime (dmaster)
        For each non-master data:
            Advance only if datetime <= dmaster
            Adjust for look-ahead if needed

    Check cheat-on-open timers
    Process broker notifications

    For each strategy:
        strategy._next()  // Process indicators + strategy logic

    Check regular timers
```

### 4.5 Multi-Data Synchronization

When multiple data feeds are present (possibly different timeframes):

1. Cortex finds the **earliest datetime** across all feeds
2. Only feeds at or before that datetime advance
3. Feeds with slower timeframes retain their previous values
4. The `oldsync=true` mode uses data0 as the master clock

This allows mixing daily and intraday data, or multiple instruments, in one strategy.

## 5. Broker Notifications

`_brokernotify()` is called each bar to deliver notifications:

1. Get pending notifications from broker
2. For each notification (order):
   a. Call `strategy.notify_order(order)` on the owning strategy
   b. If order completed or canceled, close pending trades
   c. Call `strategy.notify_trade(trade)` for affected trades

Additional notification types:
- `notify_cashvalue(cash, value)` — Portfolio updates
- `notify_fund(cash, value, fundvalue, shares)` — Fund-mode updates
- `notify_store(msg, *args, **kwargs)` — Store messages (live trading)
- `notify_data(data, status, *args, **kwargs)` — Data feed status changes

## 6. Timers

### 6.1 Timer Concept

Timers fire callbacks at specific times during trading sessions.

### 6.2 Timer Parameters

| Parameter | Description |
|-----------|-------------|
| `when` | Time of day to fire (time value or Timer constant) |
| `offset` | Duration offset from `when` |
| `repeat` | How often to repeat within the session |
| `weekdays` | List of weekday numbers (1=Mon, 7=Sun) |
| `weekcarry` | If a weekday is missed, fire on next available day |
| `monthdays` | List of month days |
| `monthcarry` | If a month day is missed, fire on next available day |
| `allow` | Callable filter: `allow(datetime) → bool` |
| `tzdata` | Data feed to use for timezone |
| `cheat` | Fire before broker processing (cheat-on-open) |

### 6.3 Timer Constants

- `SESSION_START`: Fire at session open
- `SESSION_END`: Fire at session close

### 6.4 Timer Execution

Timers are checked twice per bar:
1. **Cheat timers** (`cheat=true`): Fired before broker processes orders
2. **Regular timers** (`cheat=false`): Fired after strategy.next()

When a timer fires, `strategy.notify_timer(timer, when, *args, **kwargs)` is called.

## 7. Optimization

### 7.1 Parameter Grid

```
cortex.optstrategy(MyStrategy,
    period=range(10, 30),      // 20 values
    factor=[1.5, 2.0, 2.5],   // 3 values
)
// Total combinations: 60
```

### 7.2 Parallel Execution

When `maxcpus` != 1:
1. A process pool is created
2. Each parameter combination is serialized and sent to a worker
3. Workers run independent backtests
4. Results are collected and returned

### 7.3 Optimization Shortcuts

- `optdatas=true`: Data is preloaded once in the main process and passed to workers (avoids re-reading files)
- `optreturn=true`: Only params + analyzer results are returned (not full strategy objects with all data)

### 7.4 Serialization for Workers

Each worker receives a serialized task containing:

| Component | Serialization Approach |
|-----------|----------------------|
| Strategy class | Class reference (module path + class name) |
| Parameters | Dictionary of `{param_name: value}` for this combination |
| Data feeds | Serialized line arrays if `optdatas=true`; otherwise, data source references (file paths, API config) for the worker to load independently |
| Broker config | Commission schemes, slippage settings, initial cash |
| Analyzers/Observers | Class references + parameter dictionaries |

Workers reconstruct the full Cortex environment from these components and run an independent backtest.

### 7.5 Data Sharing (`optdatas=true`)

When `optdatas=true`:

1. The main process preloads all data feeds into memory
2. Preloaded line arrays are serialized once and included in each worker's task
3. Workers reconstruct data feeds from the serialized arrays (no file I/O)
4. This avoids redundant file reads across all optimization runs

When `optdatas=false` (or data cannot be preloaded):

1. Each worker receives data source references (file paths, connection config)
2. Workers independently load data from source
3. Slower but uses less memory for serialization

### 7.6 OptReturn (Lightweight Results)

When `optreturn=true`, workers return an `OptReturn` object instead of the full strategy:

```
OptReturn:
    params: {}              // Strategy parameter values for this run
    analyzers: {}           // Map of analyzer name → analyzer results (get_analysis())
```

This avoids serializing the full strategy object graph (all line data, indicator state, order history) back to the main process. Only the parameter combination and computed metrics are returned.

When `optreturn=false`, the full strategy object is returned, including all line data and state. This uses significantly more memory but allows post-hoc inspection of trades, indicator values, and plotting.

## 8. Plotting

See [11-plotting.md](11-plotting.md) for the full plotting specification, including `cortex.plot()` parameters, chart layout, `PlotScheme`, and per-component plot configuration (`plotinfo`, `plotlines`).

## 9. Writer Integration

See [09-analyzers-observers.md, Section 3](09-analyzers-observers.md) for the full writer specification, including the writer interface, `WriterFile` parameters, and output structure.
