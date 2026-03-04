# Bucktrader Examples

Runnable examples demonstrating core bucktrader features using real market data (AAPL, MSFT, SPY daily prices from 2020–2024).

## Running

From the project root:

```bash
python examples/buy_and_hold.py
python examples/sma_crossover.py
python examples/rsi_mean_reversion.py
python examples/macd_strategy.py
python examples/multi_data.py
python examples/optimization.py
```

Each script is self-contained — no arguments needed. Output goes to stdout.

## Examples

### buy_and_hold.py

Simplest possible strategy: buy AAPL on the first bar and hold until the end. Demonstrates loading CSV data with `GenericCSVData`, the `Returns` and `DrawDown` analyzers, and printing a performance summary.

### sma_crossover.py

Classic trend-following strategy using two Simple Moving Averages. Buys on a golden cross (fast SMA crosses above slow SMA), sells on a death cross. Demonstrates the `SMA` indicator, parameterized strategies, and the `SharpeRatio` and `TradeAnalyzer` analyzers.

### rsi_mean_reversion.py

Mean reversion strategy on MSFT using the Relative Strength Index. Buys when RSI drops below 30 (oversold), sells when RSI rises above 70 (overbought). Demonstrates the `RSI` indicator and configurable strategy parameters.

### macd_strategy.py

Trades SPY based on MACD histogram zero-crossings. Buys when the histogram turns positive, sells when it turns negative. Demonstrates the `MACDHisto` indicator.

### multi_data.py

Portfolio strategy trading AAPL, MSFT, and SPY simultaneously. Uses an SMA filter on each instrument independently. Demonstrates loading multiple data feeds, iterating over all feeds in a strategy, and per-instrument position management.

### optimization.py

Grid search over fast and slow SMA periods for a crossover strategy on AAPL. Tests 16 parameter combinations and ranks them by total return. Demonstrates `optstrategy`, `OptReturn` result objects, and collecting/sorting optimization results.

## Data

The `data/` directory contains daily OHLCV CSV files downloaded from Yahoo Finance:

| File | Ticker | Period | Bars |
|------|--------|--------|------|
| `aapl.csv` | Apple (AAPL) | 2020-01-02 to 2024-12-31 | 1,257 |
| `msft.csv` | Microsoft (MSFT) | 2020-01-02 to 2024-12-31 | 1,257 |
| `spy.csv` | S&P 500 ETF (SPY) | 2020-01-02 to 2024-12-31 | 1,257 |

CSV format: `Date,Open,High,Low,Close,Volume,OpenInterest`
