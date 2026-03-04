# Getting Started

## Requirements

- Python 3.11+
- `pip` or another modern Python package manager

## Installation

```bash
git clone <your-repo-url>
cd bucktrader
pip install -e ".[dev,docs]"
```

## Verify Installation

Run the test suite:

```bash
pytest
```

If tests pass, your environment is ready.

## Project Layout

- `bucktrader/` - framework runtime code
- `tests/` - unit and integration tests
- `docs/` - specification and user guides
- `mkdocs.yml` - documentation site configuration

## Next Steps

1. Follow `Quick Start` to run a basic strategy.
2. Read `Strategies`, `Indicators`, and `Broker` guides.
3. Use `API Reference` for detailed module/class docs.
