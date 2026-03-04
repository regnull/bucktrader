# Bucktrader Specification: Data Feeds

## 1. Concept

A data feed is a source of time series market data. It inherits from the Lines system and provides standard OHLCV lines plus a datetime line. Data feeds abstract the source (files, databases, APIs, live streams) behind a uniform interface.

## 2. Standard Lines

Every data feed provides these lines in a fixed order:

| Index | Name | Description |
|-------|------|-------------|
| 0 | `datetime` | Bar timestamp (float, days-since-epoch encoding) |
| 1 | `open` | Opening price |
| 2 | `high` | High price |
| 3 | `low` | Low price |
| 4 | `close` | Closing price |
| 5 | `volume` | Trading volume |
| 6 | `openinterest` | Open interest (futures) |

Data feeds may define additional lines beyond these seven (e.g., `adjclose` for adjusted close).

## 3. DataSeries and TimeFrame

### 3.1 TimeFrame

An enumeration defining granularity levels:

| Constant | Value | Description |
|----------|-------|-------------|
| `Ticks` | 0 | Individual ticks |
| `MicroSeconds` | 1 | Microsecond bars |
| `Seconds` | 2 | Second bars |
| `Minutes` | 3 | Minute bars |
| `Days` | 4 | Daily bars |
| `Weeks` | 5 | Weekly bars |
| `Months` | 6 | Monthly bars |
| `Years` | 7 | Yearly bars |
| `NoTimeFrame` | 8 | No time constraint |

### 3.2 Compression

A multiplier on the timeframe. `timeframe=Minutes, compression=5` means 5-minute bars. Default is 1.

## 4. Class Hierarchy

```
OHLCDateTime (LineSeries with datetime + OHLC lines)
└── AbstractDataBase
    ├── DataBase (primary base for all feeds)
    │   ├── CSVDataBase (file-based CSV feeds)
    │   │   ├── GenericCSVData
    │   │   └── Other format-specific CSV feeds
    │   ├── DataFrameData (tabular data input)
    │   ├── DataClone (clone of existing data)
    │   ├── DataFiller (fills gaps)
    │   ├── DataFilter (abstract filter)
    │   └── Live feeds (IBData, OandaData, etc.)
    └── FeedBase (container that holds multiple DataBase instances)
```

## 5. DataBase Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `dataname` | `null` | Primary data source identifier (filename, URL, symbol) |
| `name` | `""` | Friendly name for the feed |
| `compression` | `1` | Bar compression factor |
| `timeframe` | `Days` | Base timeframe |
| `fromdate` | `null` | Start date filter (datetime) |
| `todate` | `null` | End date filter (datetime) |
| `sessionstart` | `null` | Trading session start time |
| `sessionend` | `null` | Trading session end time |
| `filters` | `[]` | List of filter classes to apply |
| `tz` | `null` | Output timezone |
| `tzinput` | `null` | Input data timezone |
| `qcheck` | `0.0` | Queue check timeout (live feeds) |
| `calendar` | `null` | Trading calendar |

## 6. Data Loading Protocol

### 6.1 The `load()` Method

The main entry point for getting the next bar:

```
load() → bool
│
├── forward()  — Advance all line pointers
│
├── Try _fromstack()  — Check if filters have buffered bars
│   └── If found: apply date filters → return true/false
│
├── If stack empty: call _load()  — Read from source
│   └── If no data: check _fromstack again → return false if empty
│
├── Apply filters (this._filters)
│   └── Filters may consume the bar, modify it, or push bars to stack
│
├── Apply date filters (fromdate / todate)
│   └── Skip bars outside the requested range
│
└── Return true if bar accepted, false if no more data
```

### 6.2 The `_load()` Method (Override Point)

Subclasses override this to read from their specific source. Must:

1. Read the next bar from the data source
2. Set values on all lines at index `[0]`:
   ```
   lines.datetime[0] = date2num(dt)
   lines.open[0] = open_price
   lines.high[0] = high_price
   lines.low[0] = low_price
   lines.close[0] = close_price
   lines.volume[0] = volume
   lines.openinterest[0] = oi
   ```
3. Return `true` if a bar was loaded, `false` if no more data

### 6.3 Preloading

When `cortex.params.preload=true`:

```
preload():
    while load():
        pass
    _last()  // Notify final filters
    home()   // Reset pointer to beginning
```

All bars are loaded into memory, then the pointer is reset. During execution, bars are accessed by advancing the pointer.

## 7. Filter System

### 7.1 Concept

Filters transform data between loading and delivery to strategies. They sit in a pipeline and can:

- Modify bar values
- Remove bars
- Insert synthetic bars
- Aggregate bars (resampling)
- Replay bar construction

### 7.2 Filter Interface

```
Filter:
    constructor(data):
        // Setup. Receive the data feed being filtered.

    call(data):
        // Called for each bar.
        // Return false to keep the bar, true to consume it.
        // May push synthetic bars via data._add2stack() or data._save2stack()
        return false

    last(data):
        // Called after all data is exhausted.
        // Opportunity to flush remaining buffered bars.
```

### 7.3 Simple Filters

A convenience wrapper for filters that just test a condition:

```
my_filter(data):
    return data.close[0] < data.open[0]  // Filter out bearish bars
```

Return `true` to remove the bar, `false` to keep it.

### 7.4 Built-in Filters

| Filter | Description |
|--------|-------------|
| **Resampler** | Aggregates bars into larger timeframes (e.g., 1min → 1hour) |
| **Replayer** | Like resampler but delivers intermediate bars as they build |
| **SessionFilter** | Filters bars outside trading session times |
| **SessionFiller** | Fills gaps within trading sessions with synthetic bars |
| **CalendarDays** | Adds bars for missing calendar days |
| **DayStepsFilter** | Groups bars by day |
| **HeikinAshi** | Converts OHLC to Heikin-Ashi bars |
| **Renko** | Converts to Renko bricks |

### 7.5 Resampling

Resampling aggregates bars from a smaller timeframe to a larger one:

```
cortex.resampledata(data, timeframe=TimeFrame.Weeks, compression=1)
```

The Resampler:
1. Accumulates bars within a timeframe boundary
2. Tracks running high/low/volume
3. On boundary crossing: delivers the aggregated bar
4. Handles session end, month/year boundaries, compression

### 7.6 Replaying

Replaying is similar to resampling but delivers **intermediate** bars:

```
cortex.replaydata(data, timeframe=TimeFrame.Days, compression=1)
```

The Replayer:
1. For each tick/bar within a period: delivers an updated (partial) bar
2. The bar's high/low/close/volume are updated incrementally
3. The strategy sees the bar "building" in real-time
4. Uses `backwards()` to rewrite the previous partial bar

### 7.7 Bar Stack

Filters communicate with the data feed via two stacks:

- **`_barstack`** (queue): Main buffer. Bars pushed here are delivered before reading new source data.
- **`_barstash`** (queue): Temporary stash for look-ahead bars.

Key methods:
- `_save2stack(erase=false)`: Save current bar to stack
- `_add2stack(bar)`: Add a synthetic bar to stack
- `_fromstack()`: Pop and load a bar from stack
- `_updatebar(bar)`: Overwrite current bar with values from a bar tuple

## 8. CSV Data Feeds

### 8.1 CSVDataBase

Base class for all CSV-based feeds:

1. Opens file on `start()`
2. Reads lines, splits by separator
3. Handles headers (skip or parse)
4. Calls `_loadline(linetokens)` for each row
5. Closes file on `stop()`

**Parameters:**
| Parameter | Default | Description |
|-----------|---------|-------------|
| `headers` | `true` | First row is headers |
| `separator` | `,` | Field separator |

### 8.2 GenericCSVData

The most flexible CSV feed. Maps column positions to OHLCV fields:

```
data = GenericCSVData(
    dataname="data.csv",
    dtformat="%Y-%m-%d",
    datetime=0,    // Column index for datetime
    open=1,
    high=2,
    low=3,
    close=4,
    volume=5,
    openinterest=-1,  // -1 means not present
)
```

**Additional Parameters:**
| Parameter | Default | Description |
|-----------|---------|-------------|
| `dtformat` | `"%Y-%m-%d %H:%M:%S"` | Date parsing format (string or callable) |
| `tmformat` | `"%H:%M:%S"` | Time parsing format |
| `datetime` | `0` | Column index for datetime |
| `time` | `-1` | Separate time column (-1 = none) |
| `open` | `1` | Column index for open |
| `high` | `2` | Column index for high |
| `low` | `3` | Column index for low |
| `close` | `4` | Column index for close |
| `volume` | `5` | Column index for volume |
| `openinterest` | `6` | Column index for OI |
| `nullvalue` | `NaN` | Value to use for missing fields |

## 9. Tabular Data Feed

Accepts tabular data (e.g., a DataFrame or equivalent structure) directly:

```
data = DataFrameData(
    dataname=df,          // Tabular data
    datetime="Date",      // Column name or null (use index)
    open="Open",
    high="High",
    low="Low",
    close="Close",
    volume="Volume",
    openinterest=null,    // null means not present
)
```

Column mapping accepts:
- `null`: Field not present
- `-1`: Autodetect from column name
- `string`: Column name
- `int`: Column position

## 10. Data Cloning and Chaining

### 10.1 DataClone

Creates a lightweight clone that shares the original data's lines without re-reading:

```
clone = data.clone()  // or data.copyas("new_name")
```

Used internally when the same data feed is needed in multiple places.

### 10.2 Chaining

Concatenates multiple feeds end-to-end:

```
cortex.chaindata(data1, data2, data3)
// data3 starts after data2 ends, which starts after data1 ends
```

### 10.3 Rollover

Switches between data feeds based on rollover conditions (e.g., futures contracts):

```
cortex.rolloverdata(
    contract1, contract2, contract3,
    checkdate=my_date_checker,   // function(dt, d) → bool
    checkcondition=my_condition, // function(d0, d1) → bool
)
```

## 11. Live Data Feeds

Live feeds differ from historical feeds:

1. They report `islive() → true`
2. Data arrives asynchronously via a queue
3. `_load()` blocks waiting for new data (with `qcheck` timeout)
4. They emit status notifications: `CONNECTED`, `DISCONNECTED`, `DELAYED`, `LIVE`
5. They disable preload and runonce modes

### 11.1 Status Notifications

```
DataStatus:
    LIVE = 0
    CONNECTED = 1
    DISCONNECTED = 2
    CONNBROKEN = 3
    DELAYED = 4
```

Status changes are delivered to strategies via `notify_data(data, status)`.

## 12. Creating Custom Data Feeds

### 12.1 Template

```
MyFeed extends DataBase:
    // Optional extra lines
    lines = ("custom_field",)

    // Custom parameters
    params = [
        ("api_key", ""),
        ("symbol", ""),
    ]

    start():
        super.start()
        // Initialize connection / open file / setup iterator
        source = connect(p.api_key, p.symbol)

    _load():
        bar = source.next()
        if bar is null:
            return false

        lines.datetime[0] = date2num(bar.timestamp)
        lines.open[0] = bar.open
        lines.high[0] = bar.high
        lines.low[0] = bar.low
        lines.close[0] = bar.close
        lines.volume[0] = bar.volume
        lines.openinterest[0] = 0
        lines.custom_field[0] = bar.custom
        return true

    stop():
        super.stop()
        source.disconnect()
```

### 12.2 Key Implementation Notes

- `datetime` must be a `float` from `date2num()`. Do not store raw datetime objects.
- Return `true` from `_load()` on success, `false` when no more data
- For live feeds: implement a blocking `_load()` that waits for data with a timeout
- Use `NaN` for missing values
- Call `super.start()` and `super.stop()`
