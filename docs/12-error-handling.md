# Bucktrader Specification: Error Handling and Logging

## 1. Concept

Error handling in Bucktrader follows a layered approach: errors are caught at system boundaries, propagated through notifications where possible, and only terminate execution when recovery is not possible. The framework distinguishes between recoverable errors (handled via notifications) and fatal errors (which halt execution).

## 2. Error Categories

### 2.1 Data Errors

Errors during data feed loading or processing.

| Error | Behavior | Recovery |
|-------|----------|----------|
| Missing data file | Raise error during `start()` | Fatal — cannot proceed without data |
| Malformed row (CSV) | Skip row, log warning | Continue with next row |
| Missing field value | Use `nullvalue` (default: `NaN`) | Continue |
| Date parse failure | Skip row, log warning | Continue with next row |
| Data out of range (`fromdate`/`todate`) | Skip silently | Continue (expected behavior) |
| Empty data feed | Return `false` from `load()` | Cortex handles as end-of-data |

### 2.2 Order Errors

Errors during order creation or execution.

| Error | Behavior | Recovery |
|-------|----------|----------|
| Insufficient cash/margin | Order status set to `Margin` | Strategy receives `notify_order` with `Margin` status |
| Invalid order parameters | Order status set to `Rejected` | Strategy receives `notify_order` with `Rejected` status |
| Order expired | Order status set to `Expired` | Strategy receives `notify_order` with `Expired` status |
| Broker rejection (live) | Order status set to `Rejected` | Strategy receives `notify_order` with `Rejected` status |

Order errors never terminate execution. They are always delivered as notifications.

### 2.3 Connection Errors (Live Trading)

Errors in the connection to external services.

| Error | Behavior | Recovery |
|-------|----------|----------|
| Initial connection failure | Raise error during `start()` | Fatal — cannot start without connection |
| Connection lost | Emit `CONNBROKEN` status | Store attempts reconnection (configurable retries) |
| Reconnection failed | Emit `DISCONNECTED` status | Strategy receives notification, can decide to halt |
| Timeout waiting for data | `_load()` returns after `qcheck` timeout | Cortex retries on next iteration |
| API error response | Log error, emit store notification | Strategy receives `notify_store` |

### 2.4 User Code Errors

Errors in user-written strategy, indicator, or analyzer code.

| Error | Behavior | Recovery |
|-------|----------|----------|
| Exception in `next()` / `prenext()` | Propagate to Cortex main loop | Fatal — terminates backtest |
| Exception in `__init__()` | Propagate during strategy construction | Fatal — terminates before run |
| Exception in `notify_*()` callbacks | Propagate to Cortex main loop | Fatal — terminates backtest |
| Exception in `stop()` | Log error, continue teardown | Non-fatal — other strategies still call `stop()` |
| Index out of range on line access | Raise error | Fatal — indicates logic error |

### 2.5 Parameter Validation Errors

| Error | Behavior | Recovery |
|-------|----------|----------|
| Unknown parameter name | Log warning | Ignored — uses defaults |
| Invalid parameter type | Raise error during construction | Fatal — fix configuration |
| Missing required data feed | Raise error during construction | Fatal — indicator needs at least `_mindatas` feeds |

## 3. Error Propagation Model

```
User Code Error (next/prenext/init)
    ↓
LineIterator._next() / ._once()
    ↓
Strategy._next() / ._once()
    ↓
Cortex._runnext() / ._runonce()
    ↓
Cortex.run()
    ↓
Propagated to caller
```

Order and connection errors follow a different path — they are delivered as notifications rather than exceptions:

```
Order Error / Connection Error
    ↓
Broker.notify(order) / Store.put_notification(msg)
    ↓
Cortex._brokernotify() / Cortex._runnext() polls
    ↓
Strategy.notify_order() / Strategy.notify_store()
```

## 4. Logging

### 4.1 Log Levels

| Level | Usage |
|-------|-------|
| `ERROR` | Unrecoverable errors that will terminate execution |
| `WARNING` | Recoverable issues (skipped rows, unknown params, connection retries) |
| `INFO` | Major lifecycle events (strategy start/stop, data feed connect/disconnect, order fills) |
| `DEBUG` | Detailed execution trace (bar processing, indicator computation, order matching) |

### 4.2 What Gets Logged

| Component | INFO Events | DEBUG Events |
|-----------|-------------|-------------|
| Cortex | Run start/end, strategy instantiation | Bar processing, synchronization decisions |
| Data Feed | Connect, disconnect, backfill start/end | Each bar loaded, filter actions |
| Broker | Order fills, position changes | Order matching attempts, slippage calculations |
| Strategy | Start, stop | Each `next()` call, order submissions |
| Store | Connection, reconnection | API calls, message processing |

### 4.3 Configuration

Logging is configured at the Cortex level:

```
cortex = Cortex()
cortex.params.loglevel = "INFO"     // Minimum log level
cortex.params.logfile = null         // null = stderr, string = file path
```

## 5. Recovery Patterns (Live Trading)

### 5.1 Connection Recovery

Stores implement automatic reconnection:

```
On connection lost:
    1. Emit CONNBROKEN status notification
    2. Attempt reconnect (up to `reconnect` attempts)
    3. Wait `timeout` seconds between attempts
    4. On success: emit CONNECTED, then LIVE when data resumes
    5. On failure: emit DISCONNECTED
```

### 5.2 Data Gap Recovery

When a live feed reconnects after a gap:

1. Request backfill data to cover the gap period
2. Deliver backfill bars (status = `DELAYED`)
3. Transition to live streaming (status = `LIVE`)
4. Strategy continues processing normally

### 5.3 Order State Recovery

When a live broker reconnects:

1. Query all open orders from the external broker
2. Reconcile with internal order tracking
3. Deliver any missed fill notifications
4. Sync position and cash balances
