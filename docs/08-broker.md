# Bucktrader Specification: Broker and Order System

## 1. Concept

The broker is responsible for:

- Receiving and managing orders
- Simulating order execution against market data (backtesting) or routing to real exchanges (live)
- Tracking positions and portfolio value
- Calculating commissions and margin requirements
- Managing cash and credit

## 2. Broker Interface (BrokerBase)

All brokers implement this interface:

### 2.1 Order Methods

```
buy(owner, data, size, price, plimit, exectype, valid, tradeid,
    oco, trailamount, trailpercent, parent, transmit, **kwargs)
    → Order

sell(owner, data, size, price, plimit, exectype, valid, tradeid,
     oco, trailamount, trailpercent, parent, transmit, **kwargs)
    → Order

cancel(order) → void
```

### 2.2 Portfolio Methods

```
getvalue(datas=null)      → float     // Total portfolio value
getcash()                 → float     // Available cash
getposition(data)         → Position  // Position for a data feed
get_fundshares()          → float     // Fund shares (fund mode)
get_fundvalue()           → float     // Fund value per share
```

### 2.3 Lifecycle Methods

```
start()    // Called when backtest begins
stop()     // Called when backtest ends
next()     // Called each bar to process pending orders
```

### 2.4 Notification Methods

```
get_notification()  → Order or null   // Pop next notification
notify(order)                          // Queue notification
```

## 3. BackBroker (Backtesting Broker)

The default simulated broker for backtesting.

### 3.1 Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `cash` | `10000.0` | Starting cash |
| `commission` | - | Default commission scheme |
| `checksubmit` | `true` | Verify margin/cash before accepting orders |
| `eosbar` | `false` | Close-of-day orders execute on same bar |
| `filler` | `null` | Volume filler for partial fills |
| `slip_perc` | `0.0` | Slippage percentage |
| `slip_fixed` | `0.0` | Fixed slippage amount |
| `slip_open` | `false` | Apply slippage to open price |
| `slip_match` | `true` | Match slipped price to high/low range |
| `slip_limit` | `true` | Apply slippage to limit orders |
| `slip_out` | `false` | Allow slippage outside bar range |
| `coc` | `false` | Cheat-on-close (execute at this bar's close) |
| `coo` | `false` | Cheat-on-open (execute at next bar's open) |
| `int2pnl` | `true` | Include interest in P&L |
| `shortcash` | `true` | Short sales generate cash |
| `fundstartval` | `100.0` | Initial fund share value |
| `fundmode` | `false` | Track as fund (NAV per share) |
| `tradehistory` | `false` | Log detailed trade history |

### 3.2 Execution Flow (next method)

Each bar, the broker performs:

```
1. Activate pending orders (waiting for transmit)
2. Check submitted orders (verify margin if checksubmit=true)
3. Deduct credit interest for open positions
4. Process order history (if using historical orders)
5. For each pending order:
   a. Check expiration → cancel if expired
   b. Check if active → skip if not yet active
   c. Try to execute (_try_exec):
      - Match against current bar's OHLC
      - Apply slippage
      - Apply volume filler (partial fills)
      - Execute fill
   d. If completed: process bracket orders
6. Adjust cash for futures position changes (mark-to-market)
7. Recalculate portfolio value
```

## 4. Order

### 4.1 Order Status Lifecycle

```
Created → Submitted → Accepted → Partial → Completed
                                         → Canceled
                                         → Expired
                                         → Margin (rejected for margin)
                                         → Rejected
```

### 4.2 Order Properties

| Property | Description |
|----------|-------------|
| `ref` | Unique order reference number |
| `status` | Current status (see above) |
| `data` | Data feed this order is for |
| `size` | Requested size |
| `price` | Requested price |
| `pricelimit` | Price limit (StopLimit orders) |
| `exectype` | Execution type |
| `valid` | Validity datetime |
| `tradeid` | Trade group identifier |
| `oco` | One-Cancels-Other linked order |
| `parent` | Parent order (bracket orders) |
| `created` | OrderData at creation time |
| `executed` | OrderData tracking execution |
| `trailamount` | Trailing stop distance |
| `trailpercent` | Trailing stop percentage |

### 4.3 OrderData

Tracks execution details:

| Field | Description |
|-------|-------------|
| `dt` | Datetime of event |
| `size` | Size executed (or remaining) |
| `remsize` | Remaining size to fill |
| `price` | Execution price |
| `value` | Total value (price * size) |
| `comm` | Commission charged |
| `pnl` | Profit/loss on this execution |
| `margin` | Margin required |

### 4.4 Execution Bits

Each partial fill creates an `OrderExecutionBit` recording:
- Datetime, size, price, closed amount, opened amount
- Running P&L, value, commission

### 4.5 Order Validity

| Type | Description |
|------|-------------|
| `null` | Good-till-canceled (no expiration) |
| `datetime` | Valid until this datetime |
| `duration` | Valid for this duration from creation |
| `int` | Valid for this many bars |
| `float(0.0)` | Valid for current session only (DAY order) |

## 5. Order Execution Logic

### 5.1 Market Orders

Execute at the next bar's open price (or current close if `coc=true`):

```
If cheat_on_close (coc):
    Execute at current bar's close
Else if cheat_on_open (coo):
    Execute at current bar's open
Else:
    Execute at next bar's open
```

### 5.2 Close Orders

Execute at the current bar's close price. Behaves like coc=true for market orders.

### 5.3 Limit Orders

```
Buy Limit:
    If bar.low <= limit_price:
        Execute at min(limit_price, bar.open)

Sell Limit:
    If bar.high >= limit_price:
        Execute at max(limit_price, bar.open)
```

The `open` price is used if it's already better than the limit (gap scenario).

### 5.4 Stop Orders

```
Buy Stop:
    If bar.high >= stop_price:
        Execute at max(stop_price, bar.open)

Sell Stop:
    If bar.low <= stop_price:
        Execute at min(stop_price, bar.open)
```

### 5.5 StopLimit Orders

Two phases:
1. **Trigger**: Stop price is hit (same logic as stop orders)
2. **Execute**: Limit order at `plimit` price (same logic as limit orders)

### 5.6 Trailing Stop Orders

The stop price adjusts as the market moves favorably:

```
Buy StopTrail (for short positions):
    trail_price = bar.low + trail_amount  (or bar.low * (1 + trail_percent))
    stop_price = min(previous_stop, trail_price)
    If bar.high >= stop_price: execute

Sell StopTrail (for long positions):
    trail_price = bar.high - trail_amount  (or bar.high * (1 - trail_percent))
    stop_price = max(previous_stop, trail_price)
    If bar.low <= stop_price: execute
```

### 5.7 OCO (One-Cancels-Other)

When any order in an OCO group is filled or canceled, all other orders in the group are canceled.

### 5.8 Bracket Orders

A bracket creates three linked orders:
1. **Parent** (entry): Main order
2. **Child 1** (stop): Stop-loss — canceled if take-profit fills
3. **Child 2** (limit): Take-profit — canceled if stop-loss fills

The children are activated only after the parent fills.

## 6. Slippage Model

### 6.1 Types

| Parameter | Description |
|-----------|-------------|
| `slip_perc` | Percentage of price (e.g., 0.01 = 1% slippage) |
| `slip_fixed` | Fixed amount added/subtracted from price |
| `slip_open` | Also apply slippage to open price executions |
| `slip_match` | Clamp slipped price to bar's high/low range |
| `slip_limit` | Apply slippage to limit orders |
| `slip_out` | Allow slippage to push price outside bar range |

### 6.2 Application

```
Buy: execution_price = matched_price + slip_amount
Sell: execution_price = matched_price - slip_amount
```

If `slip_match=true` and slipped price exceeds bar range, it's clamped to high (buy) or low (sell).

## 7. Volume Fillers

Fillers control partial order execution based on available volume:

### 7.1 Built-in Fillers

| Filler | Description |
|--------|-------------|
| `FixedSize` | Maximum `size` units per bar, limited by bar volume |
| `FixedBarPerc` | Execute up to `perc`% of bar volume |
| `BarPointPerc` | Distribute volume across price range, take `perc`% at execution price |

### 7.2 Filler Interface

```
MyFiller:
    call(order, price, ago):
        // order: the order being filled
        // price: execution price
        // ago: bar offset (0 = current)
        // Return: maximum size that can be filled this bar
        return min(order.data.volume[ago], abs(order.executed.remsize))
```

When a filler returns less than the remaining order size, the order remains partially filled and continues to the next bar.

## 8. Commission Schemes

### 8.1 CommInfoBase

The base class for all commission models:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `commission` | `0.0` | Commission rate |
| `mult` | `1.0` | Contract multiplier (futures) |
| `margin` | `null` | Margin requirement (null = stock-like, value = futures-like) |
| `commtype` | `null` | `COMM_PERC` (percentage) or `COMM_FIXED` (per unit) |
| `stocklike` | `false` | true for stocks, false for futures |
| `percabs` | `false` | If true, commission is absolute percentage (0.01 = 1%) |
| `interest` | `0.0` | Annual interest rate for short positions |
| `interest_long` | `false` | Also charge interest on long positions |
| `leverage` | `1.0` | Leverage factor |
| `automargin` | `false` | Auto-calculate margin from price * mult |

### 8.2 Key Methods

```
getsize(price, cash)            → int    // Max shares affordable
getoperationcost(size, price)   → float  // Cost to open position
getvaluesize(size, price)       → float  // Value of position
getcommission(size, price)      → float  // Commission amount
profitandloss(size, price, newprice) → float  // P&L calculation
cashadjust(size, price, newprice)    → float  // Cash adjustment (futures)
get_credit_interest(data, pos, dt)   → float  // Interest charge
```

### 8.3 Stock vs. Futures

**Stocks (`stocklike=true`):**
- Cash is deducted for position value: `cash -= size * price`
- No margin requirement
- P&L realized on close only
- Commission as percentage or fixed per share

**Futures (`margin` is set):**
- Only margin is deducted from cash
- Positions are marked-to-market daily via `cashadjust()`
- P&L flows through cash each bar
- Contract multiplier applies: `value = size * price * mult`

### 8.4 Setting Commission

```
cortex.broker.setcommission(commission=0.001)  // 0.1% of trade value

// Or with full control:
cortex.broker.addcommissioninfo(
    CommInfoBase(commission=0.001, stocklike=true),
    name="AAPL"  // Per-instrument commission
)
```

## 9. Position

### 9.1 Properties

| Property | Description |
|----------|-------------|
| `size` | Number of units (positive=long, negative=short, 0=flat) |
| `price` | Average entry price |
| `adjbase` | Last adjustment price (for futures mark-to-market) |
| `datetime` | Last update datetime |

### 9.2 Update Logic

When a trade occurs:

```
If opening or adding to position:
    new_price = (old_price * old_size + trade_price * trade_size) / new_size

If reducing position:
    price stays the same (FIFO-like)

If closing and reopening (reversing):
    old position closes, new position opens at trade price
```

## 10. Trade

### 10.1 Concept

A Trade represents a round-trip: entry → (optional adds) → exit. Trades track P&L and provide history.

### 10.2 Properties

| Property | Description |
|----------|-------------|
| `ref` | Unique trade reference |
| `status` | `Created`, `Open`, `Closed` |
| `data` | Data feed traded |
| `tradeid` | Trade group identifier |
| `size` | Current position size in this trade |
| `price` | Average entry price |
| `value` | Current position value |
| `commission` | Total commission paid |
| `pnl` | Gross P&L |
| `pnlcomm` | Net P&L (after commission) |
| `isopen` | true if trade is currently open |
| `isclosed` | true if trade just closed |
| `justopened` | true if trade just opened |
| `baropen` | Bar number at open |
| `barclose` | Bar number at close |
| `barlen` | Duration in bars |
| `dtopen` | Datetime at open |
| `dtclose` | Datetime at close |
| `history` | List of trade update events |

### 10.3 Trade History

When `tradehistory=true`, each order execution that affects a trade records:

```
TradeHistory(
    status=status_tuple,   // (status, event fields...)
    event=event_tuple,     // (order_ref, size, price, commission, ...)
)
```

## 11. Fund Mode

When `fundmode=true`:

- The broker tracks portfolio as a fund with shares and NAV
- Initial fund value and shares are configurable
- `get_fundvalue()` returns NAV per share
- `get_fundshares()` returns total shares
- Cash additions/withdrawals adjust share count, not NAV
- Useful for benchmarking against real fund performance
