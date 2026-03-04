# Bucktrader Specification: Live Trading and Stores

## 1. Concept

Live trading extends the backtesting framework to connect with real brokers and real-time data feeds. The key abstraction is the **Store** — a singleton that manages the connection to an external service and provides both data feeds and a broker.

The design principle: strategy code should be identical for backtesting and live trading. Only the data feed and broker configuration change.

## 2. Store

### 2.1 Purpose

A Store is a connection manager that:

- Maintains a singleton connection to an external service
- Provides factory methods for creating data feeds and brokers
- Manages the lifecycle of the connection
- Delivers notifications about connection status

### 2.2 Store Interface

```
Store:
    BrokerCls = null   // Associated broker class
    DataCls = null      // Associated data class

    start(data=null, broker=null):
        // Initialize the connection.
        // Called by Cortex when data/broker starts.
        // May be called multiple times (once per data + once for broker).

    stop():
        // Close the connection.

    getdata(*args, **kwargs):
        // Factory: create a data feed connected to this store.
        data = DataCls(*args, **kwargs)
        data._store = this
        return data

    getbroker(*args, **kwargs):
        // Factory: create a broker connected to this store.
        broker = BrokerCls(*args, **kwargs)
        broker._store = this
        return broker

    put_notification(msg, *args, **kwargs):
        // Queue a notification message.
        notifs.append((msg, args, kwargs))

    get_notifications():
        // Return and clear all pending notifications.
```

### 2.3 Singleton Pattern

Stores use a singleton pattern ensuring only one instance exists per store class. Multiple data feeds and the broker all share the same store instance and connection.

### 2.4 Built-in Stores

| Store | Service | Capabilities |
|-------|---------|-------------|
| **IBStore** | Interactive Brokers (TWS/Gateway) | Historical data, real-time data, order execution |
| **OandaStore** | OANDA (forex broker) | Historical data, real-time streaming, order execution |
| **VCStore** | VisualChart | Historical data, real-time data, order execution |

## 3. Live Data Feed Behavior

### 3.1 Differences from Historical Feeds

| Aspect | Historical | Live |
|--------|-----------|------|
| `islive()` | Returns `false` | Returns `true` |
| Data arrival | Synchronous read | Asynchronous queue |
| `_load()` | Read next record | Block/poll for next bar |
| Preload | Supported | Disabled |
| Runonce | Supported | Disabled |
| Status | N/A | Connection status notifications |
| Backfill | N/A | Historical data on connect, then live |

### 3.2 Data Status Notifications

Live feeds notify strategies about their connection state:

| Status | Value | Description |
|--------|-------|-------------|
| `LIVE` | 0 | Receiving real-time data |
| `CONNECTED` | 1 | Connected but not yet streaming |
| `DISCONNECTED` | 2 | Graceful disconnection |
| `CONNBROKEN` | 3 | Connection lost unexpectedly |
| `DELAYED` | 4 | Data is delayed (not real-time) |

```
notify_data(data, status, *args, **kwargs):
    if status == data.LIVE:
        print("Receiving live data")
    elif status == data.DISCONNECTED:
        print("Data feed disconnected")
```

### 3.3 Queue-Based Loading

Live feeds use a thread-safe queue:

```
External Thread → [data queue] → _load() reads from queue
```

The `qcheck` parameter controls how often the queue is polled (in seconds). A value of 0.0 means block until data arrives.

### 3.4 Backfilling

When a live feed connects, it typically:

1. Requests historical data to fill the backfill period
2. Transitions to live streaming
3. Notifies `DELAYED` during backfill, `LIVE` when caught up

This ensures indicators have enough history to produce valid values before live trading begins.

## 4. Live Broker Behavior

### 4.1 Differences from Backtesting Broker

| Aspect | BackBroker | Live Broker |
|--------|-----------|-------------|
| Execution | Simulated against OHLC bars | Routed to exchange |
| Fill prices | Based on bar data | Actual market fills |
| Position sync | Calculated internally | Synchronized with broker |
| Notifications | Immediate | Asynchronous |
| Order types | All supported | Broker-dependent |
| Commissions | Configured locally | May come from broker |

### 4.2 Order Flow (Live)

```
Strategy.buy() → Live Broker → External API → Exchange
                                    ↓
                              Fill notification
                                    ↓
                 Live Broker ← External API
                      ↓
              Strategy.notify_order()
```

### 4.3 Position Synchronization

Live brokers periodically sync:
- Open positions
- Cash balance
- Portfolio value
- Pending orders

This ensures the internal state matches the broker's actual state, handling fills and events that happen between bar updates.

## 5. Interactive Brokers Integration

### 5.1 IBStore

Connects via the IB API (TWS or Gateway):

**Parameters:**
| Parameter | Default | Description |
|-----------|---------|-------------|
| `host` | `"127.0.0.1"` | TWS/Gateway host |
| `port` | `7496` | TWS/Gateway port |
| `clientId` | `null` | Client ID (null = auto-increment) |
| `notifyall` | `false` | Forward all IB messages as notifications |
| `_debug` | `false` | Enable debug logging |
| `reconnect` | `3` | Reconnection attempts |
| `timeout` | `3.0` | Connection timeout (seconds) |
| `timeoffset` | `true` | Sync time with IB server |
| `timerefresh` | `60.0` | Time sync refresh interval |
| `indcash` | `true` | Treat IND as cash-like |

### 5.2 IBData (Data Feed)

**Key Parameters:**
| Parameter | Default | Description |
|-----------|---------|-------------|
| `sectype` | `"STK"` | Security type: STK, FUT, OPT, CASH, CFD, etc. |
| `exchange` | `"SMART"` | Exchange |
| `currency` | `""` | Currency |
| `rtbar` | `false` | Use 5-second real-time bars |
| `historical` | `false` | Request historical data only |
| `what` | `null` | Data type: TRADES, MIDPOINT, BID, ASK |
| `useRTH` | `false` | Regular trading hours only |
| `backfill` | `true` | Backfill on connect |
| `backfill_start` | `true` | Backfill on initial connection |
| `backfill_from` | `null` | Historical data feed for initial backfill |
| `latethrough` | `false` | Allow late bars through |
| `tradename` | `null` | Trading contract name (if different from data contract) |

### 5.3 IBBroker

Routes orders to Interactive Brokers:
- Supports all IB order types
- Handles partial fills
- Manages OCO and bracket orders
- Syncs positions and account values

## 6. OANDA Integration

### 6.1 OandaStore

Connects to OANDA's REST API for forex trading:

**Parameters:**
| Parameter | Default | Description |
|-----------|---------|-------------|
| `token` | `""` | API access token |
| `account` | `""` | Account ID |
| `practice` | `false` | Use practice/demo account |

### 6.2 OandaData

Streams forex price data:
- Supports multiple granularities (S5, M1, M5, H1, D, etc.)
- Includes bid/ask spreads
- Real-time streaming via REST polling or streaming API

### 6.3 OandaBroker

Executes forex orders via OANDA:
- Market, limit, and stop orders
- Take profit and stop loss
- Trailing stops

## 7. Trading Calendars

### 7.1 Purpose

Trading calendars define:
- Trading days (excluding weekends and holidays)
- Trading sessions (open/close times)
- Early close days

### 7.2 Calendar Interface

```
TradingCalendarBase:
    _nextday(day):
        // Return the next trading day after 'day'

    schedule(day, tz=null):
        // Return (market_open, market_close) times for 'day'
```

### 7.3 Built-in Calendars

| Calendar | Description |
|----------|-------------|
| `TradingCalendar` | Custom calendar with configurable holidays and early closes |
| `ExchangeCalendar` | Wraps exchange-specific market calendar libraries for standard schedules |

### 7.4 Usage

```
// Using a standard exchange calendar
cortex.addcalendar("NYSE")

// Using a custom calendar
cal = TradingCalendar(
    holidays=["2024-01-01", "2024-12-25"],
    earlydays=[("2024-12-24", time(13, 0))],
    open=time(9, 30),
    close=time(16, 0),
)
cortex.addcalendar(cal)
```

Calendars affect:
- Timer firing (session start/end detection)
- Data feed filtering (skip non-trading days)
- Resampling bar boundaries

## 8. Notification System

### 8.1 Notification Flow

```
External Event (fill, connection, error)
    ↓
Store.put_notification(msg)
    ↓
Cortex._runnext() polls store notifications
    ↓
Strategy.notify_store(msg)
    ↓
Strategy.notify_data(data, status)  [for data status changes]
```

### 8.2 Store Notifications

Delivered to strategies as generic messages:

```
notify_store(msg, *args, **kwargs):
    // msg is typically a string describing the event
    print("Store notification: " + msg)
```

### 8.3 Data Notifications

```
notify_data(data, status, *args, **kwargs):
    status_names = {
        data.LIVE: "LIVE",
        data.CONNECTED: "CONNECTED",
        data.DISCONNECTED: "DISCONNECTED",
        data.CONNBROKEN: "CONNBROKEN",
        data.DELAYED: "DELAYED",
    }
    print("Data " + data._name + ": " + status_names.get(status, "UNKNOWN"))
```

## 9. Live vs. Backtest Mode Selection

Mode is determined automatically:

```
If any data.islive() returns true:
    → Live mode
    → preload = false
    → runonce = false

Else if cortex.params.live = true:
    → Forced live mode
    → preload = false
    → runonce = false

Else:
    → Backtest mode
    → preload and runonce as configured
```

## 10. Implementation Guidance for Live Trading

### 10.1 Store Implementation

To add support for a new broker/data source:

1. Create a `Store` subclass (singleton)
2. Implement connection management (connect, disconnect, reconnect)
3. Implement data streaming (typically via background thread + queue)
4. Implement order routing and fill notification
5. Set `DataCls` and `BrokerCls` class attributes

### 10.2 Live Data Feed Implementation

1. Extend `DataBase`
2. Override `islive()` to return `true`
3. Implement `_load()` to read from a queue (with timeout via `qcheck`)
4. Emit status notifications via the store
5. Handle backfilling on initial connection
6. Handle reconnection and data gaps

### 10.3 Live Broker Implementation

1. Extend `BrokerBase`
2. Implement `buy()`, `sell()`, `cancel()` to route to external API
3. Implement `next()` to poll for fills and position updates
4. Implement `getvalue()`, `getcash()`, `getposition()` to reflect actual broker state
5. Queue notifications for completed/canceled orders
