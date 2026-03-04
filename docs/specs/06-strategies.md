# Bucktrader Specification: Strategies

## 1. Concept

A Strategy is the user's trading logic. It receives market data, evaluates conditions using indicators, and issues orders through a broker. Strategies are the primary extension point for users.

## 2. Lifecycle

```
constructor()     ← Declare indicators, set up state
start()           ← Called once before backtesting begins
prenext()         ← Called for each bar during warmup (min period not yet met)
nextstart()       ← Called exactly once when min period is first met
next()            ← Called for each bar after warmup (main trading logic)
stop()            ← Called once after backtesting ends
```

### 2.1 Warmup Period

The strategy's minimum period is the maximum of all its indicators' minimum periods. Until that many bars have been processed:

- `prenext()` is called instead of `next()`
- Indicators may not have valid values yet
- Orders should generally not be placed during prenext

### 2.2 nextstart vs next

`nextstart()` is called exactly once — the first bar where all indicators are valid. Default implementation simply calls `next()`. Override to perform one-time initialization that requires indicator data.

### 2.3 Cheat-on-Open Mode

When `cortex.params.cheat_on_open=true`:

```
next_open()       ← Called BEFORE broker processes orders and indicators update
next()            ← Called after (normal flow)
```

This allows placing orders that use the current bar's open price for calculations while still using the previous bar's indicator values.

## 3. Data Access

### 3.1 Data Feed References

```
this.data          // First data feed (alias for datas[0])
this.data0         // Same as data
this.data1         // Second data feed
this.datas         // List of all data feeds
this.dnames        // Map of named data feeds: dnames["AAPL"]
```

### 3.2 Line Access

```
this.data.close        // Close line of first data feed
this.data.close[0]     // Current close price
this.data.close[-1]    // Previous bar's close
this.data_close        // Shortcut for data.close
this.data0_high        // High line of data0
this.data1_volume      // Volume line of data1
```

### 3.3 DateTime Access

```
this.data.datetime.date(0)      // Current bar's date
this.data.datetime.datetime(0)  // Current bar's datetime
this.data.datetime.time(0)      // Current bar's time
len(this.data)                  // Number of bars processed
```

## 4. Order API

### 4.1 Basic Orders

```
buy(data=null, size=null, price=null, plimit=null,
    exectype=null, valid=null, tradeid=0, oco=null,
    trailamount=null, trailpercent=null, parent=null,
    transmit=true, **kwargs)
    → Order

sell(data=null, size=null, price=null, plimit=null,
     exectype=null, valid=null, tradeid=0, oco=null,
     trailamount=null, trailpercent=null, parent=null,
     transmit=true, **kwargs)
    → Order
```

**Parameters:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `data` | `null` | Data feed to trade (default: first data feed) |
| `size` | `null` | Order size (default: use sizer) |
| `price` | `null` | Limit/stop price (default: market) |
| `plimit` | `null` | Price limit for StopLimit orders |
| `exectype` | `null` | Execution type (see below) |
| `valid` | `null` | Order validity: datetime, duration, or number of bars |
| `tradeid` | `0` | Trade group identifier |
| `oco` | `null` | One-Cancels-Other linked order |
| `trailamount` | `null` | Trailing stop distance (absolute) |
| `trailpercent` | `null` | Trailing stop distance (percentage) |
| `parent` | `null` | Parent order (for bracket orders) |
| `transmit` | `true` | Submit immediately (false for bracket assembly) |

### 4.2 Convenience Methods

```
close(data=null, size=null, **kwargs)
    // Close the entire position on the given data feed.
    // Equivalent to sell(size=position.size) for long, buy for short.

order_target_size(data=null, target=0, **kwargs)
    // Adjust position to reach the target size.
    // Buys or sells the difference.

order_target_value(data=null, target=0.0, price=null, **kwargs)
    // Adjust position to reach the target portfolio value.

order_target_percent(data=null, target=0.0, **kwargs)
    // Adjust position to reach target as percentage of portfolio value.
```

### 4.3 Bracket Orders

A bracket order is a group of three orders:
1. **Main order**: Entry order
2. **Stop loss**: Protective stop below (for long) or above (for short)
3. **Take profit**: Limit order above (for long) or below (for short)

When the main order fills, both stop and take profit become active. When either fills, the other is canceled.

```
buy_bracket(data=null, size=null, price=null,
            stopprice=null, stopargs={},
            limitprice=null, limitargs={},
            **kwargs)
    → [main_order, stop_order, limit_order]

sell_bracket(data=null, size=null, price=null,
             stopprice=null, stopargs={},
             limitprice=null, limitargs={},
             **kwargs)
    → [main_order, stop_order, limit_order]
```

### 4.4 Cancel

```
cancel(order)
    // Cancel a pending order.
```

## 5. Execution Types

| Type | Constant | Description |
|------|----------|-------------|
| Market | `Order.Market` | Execute at next available price |
| Close | `Order.Close` | Execute at the bar's closing price |
| Limit | `Order.Limit` | Execute at `price` or better |
| Stop | `Order.Stop` | Trigger when price reaches `price`, then execute as market |
| StopLimit | `Order.StopLimit` | Trigger at `price`, then execute as limit at `plimit` |
| StopTrail | `Order.StopTrail` | Trailing stop: adjusts with price movement |
| StopTrailLimit | `Order.StopTrailLimit` | Trailing stop with limit execution |
| Historical | `Order.Historical` | Replay historical orders (special) |

## 6. Notifications

### 6.1 Order Notifications

```
notify_order(order):
    // Called when an order's status changes.
    // order.status values: Created, Submitted, Accepted,
    //   Partial, Completed, Canceled, Expired, Margin, Rejected
```

### 6.2 Trade Notifications

```
notify_trade(trade):
    // Called when a trade changes state.
    // trade.isclosed: true if the trade just closed
    // trade.isopen: true if the trade just opened
    // trade.pnl: Gross profit/loss
    // trade.pnlcomm: Net profit/loss (after commission)
```

### 6.3 Other Notifications

```
notify_cashvalue(cash, value):
    // Portfolio cash and total value update.

notify_fund(cash, value, fundvalue, shares):
    // Fund-mode portfolio update.

notify_store(msg, *args, **kwargs):
    // Message from the store (live trading).

notify_data(data, status, *args, **kwargs):
    // Data feed status change (live trading).

notify_timer(timer, when, *args, **kwargs):
    // Timer callback.
```

## 7. Position Access

```
position = getposition(data=null)
    // Returns the Position object for the given data feed.
    // position.size: number of shares/contracts (positive=long, negative=short)
    // position.price: average entry price

this.position
    // Shortcut for getposition(data)
```

## 8. Sizers

### 8.1 Concept

Sizers determine the order size when `size=null` is passed to buy/sell. They allow strategies to focus on signal logic while delegating position sizing.

### 8.2 Sizer Interface

```
MySizer extends Sizer:
    params = [("stake", 10)]

    _getsizing(comminfo, cash, data, isbuy):
        // comminfo: commission scheme for the data
        // cash: available cash
        // data: data feed being traded
        // isbuy: true for buy, false for sell
        return p.stake
```

### 8.3 Built-in Sizers

| Sizer | Description |
|-------|-------------|
| `FixedSize` | Fixed number of shares/contracts |
| `FixedReverser` | Fixed size, doubles on reversal |
| `PercentSizer` | Percentage of available cash |
| `AllInSizer` | Use all available cash (100%) |
| `PercentSizerInt` | Percentage of cash, truncated to integer |
| `AllInSizerInt` | All cash, truncated to integer |

### 8.4 Sizer Configuration

```
cortex.addsizer(FixedSize, stake=100)                          // Global sizer
cortex.addsizer_byidx(0, PercentSizer, percents=50)           // Per-strategy
strategy.setsizer(my_sizer)                                    // Inside strategy
```

## 9. Signal-Based Trading

### 9.1 Concept

For simple strategies, signals can be used instead of writing a full `next()` method. A signal is an indicator that produces positive (buy) or negative (sell) values.

### 9.2 Signal Types

| Signal | When Positive | When Negative |
|--------|--------------|---------------|
| `LONGSHORT` | Go long | Go short |
| `LONG` | Enter long | Close long |
| `LONG_INV` | Close long | Enter long |
| `LONG_ANY` | Enter or maintain long | Close long |
| `SHORT` | Close short | Enter short |
| `SHORT_INV` | Enter short | Close short |
| `SHORT_ANY` | Close short | Enter or maintain short |
| `LONGEXIT` | Close long | - |
| `SHORTEXIT` | - | Close short |

### 9.3 Usage

```
cortex.add_signal(SIGNAL_LONGSHORT, MySignalIndicator, period=20)
```

The `SignalStrategy` processes all registered signals automatically, generating orders without requiring user code in `next()`.

### 9.4 Signal Accumulation and Concurrency

Parameters control signal behavior:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `_accumulate` | `false` | Allow adding to existing positions |
| `_concurrent` | `false` | Allow multiple pending orders |
| `_stake` | - | Fixed order size |
| `_period` | - | Signal indicator period |

## 10. Memory Management

See [01-overview.md, Section 6](01-overview.md) for the full specification of memory management modes (`cortex.params.exactbars`).

## 11. Writer Output

Strategies support data export via writers:

```
getwriterheaders():
    // Returns list of header strings for all data feeds + indicators

getwritervalues():
    // Returns list of current values for all data feeds + indicators
```

## 12. Environment Access

```
this.env              // Reference to Cortex
this.cortex           // Same as env
this.broker           // The broker instance
this._orders          // List of all orders created
this._trades          // Map of trades by data feed
this.stats            // Observers (alias: observers)
this.analyzers        // Analyzers collection
```
