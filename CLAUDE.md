# Bucktrader

Event-driven algorithmic trading framework for backtesting and live trading.

## Specifications

- [01 - Project Overview and Architecture](docs/specs/01-overview.md) - Purpose, key abstractions, memory management
- [02 - The Lines System](docs/specs/02-lines-system.md) - Core data model: time-indexed float64 arrays
- [03 - Component Model and Parameter System](docs/specs/03-component-model.md) - Component infrastructure, lifecycle hooks, LineIterator
- [04 - Cortex (Engine Orchestrator)](docs/specs/04-cortex.md) - Top-level orchestration, optimization, serialization
- [05 - Data Feeds](docs/specs/05-data-feeds.md) - Market data sources (files, databases, APIs, live streams)
- [06 - Strategies](docs/specs/06-strategies.md) - User trading logic and order issuance
- [07 - Indicators](docs/specs/07-indicators.md) - Technical analysis computations on lines
- [08 - Broker and Order System](docs/specs/08-broker.md) - Order execution and portfolio management
- [09 - Analyzers, Observers, and Writers](docs/specs/09-analyzers-observers.md) - Metrics, monitoring, output
- [10 - Live Trading and Stores](docs/specs/10-live-trading.md) - Real-time broker integration via Stores
- [11 - Plotting System](docs/specs/11-plotting.md) - Multi-panel chart rendering
- [12 - Error Handling and Logging](docs/specs/12-error-handling.md) - Error categories, recovery, logging

## Guides

- [Getting Started](docs/getting-started.md) - Installation and requirements
- [Quick Start](docs/quickstart.md) - Minimal end-to-end backtest tutorial
- [Optimization Guide](docs/optimization.md) - Parameter optimization across strategy variants
- [Example Strategies](docs/examples.md) - Small, adaptable strategy examples

## API Reference

- [API Index](docs/api/index.md) - Package overview (generated from docstrings)
- [bucktrader.cortex](docs/api/cortex.md)
- [bucktrader.strategy](docs/api/strategy.md)
- [bucktrader.broker](docs/api/broker.md)
- [bucktrader.feed](docs/api/feed.md)
- [bucktrader.indicator](docs/api/indicator.md)
- [bucktrader.analyzer](docs/api/analyzer.md)
- [bucktrader.observer](docs/api/observer.md)
- [bucktrader.order](docs/api/order.md)
- [bucktrader.trade](docs/api/trade.md)
