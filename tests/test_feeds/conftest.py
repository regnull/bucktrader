"""Shared fixtures for data feed tests.

Provides sample CSV content (20 rows of daily OHLCV data) and helper
factories used across all feed test modules.
"""

from __future__ import annotations

import io
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# ── Sample CSV data ──────────────────────────────────────────────────────────
# 20 trading days of fictional daily OHLCV data (no weekends).

SAMPLE_CSV_HEADER = "Date,Open,High,Low,Close,Volume,OpenInterest"

SAMPLE_CSV_ROWS = [
    "2024-01-02,100.00,102.50,99.50,101.00,10000,500",
    "2024-01-03,101.00,103.00,100.00,102.50,12000,510",
    "2024-01-04,102.50,104.00,101.50,103.00,11000,520",
    "2024-01-05,103.00,105.00,102.00,104.50,13000,530",
    "2024-01-08,104.50,106.50,103.50,105.00,14000,540",
    "2024-01-09,105.00,107.00,104.00,106.00,15000,550",
    "2024-01-10,106.00,108.00,105.00,107.50,13500,560",
    "2024-01-11,107.50,109.00,106.50,108.00,14500,570",
    "2024-01-12,108.00,110.00,107.00,109.50,16000,580",
    "2024-01-15,109.50,111.00,108.50,110.00,15500,590",
    "2024-01-16,110.00,112.00,109.00,111.50,17000,600",
    "2024-01-17,111.50,113.00,110.50,112.00,16500,610",
    "2024-01-18,112.00,114.00,111.00,113.50,18000,620",
    "2024-01-19,113.50,115.00,112.50,114.00,17500,630",
    "2024-01-22,114.00,116.00,113.00,115.50,19000,640",
    "2024-01-23,115.50,117.00,114.50,116.00,18500,650",
    "2024-01-24,116.00,118.00,115.00,117.50,20000,660",
    "2024-01-25,117.50,119.00,116.50,118.00,19500,670",
    "2024-01-26,118.00,120.00,117.00,119.50,21000,680",
    "2024-01-29,119.50,121.00,118.50,120.00,20500,690",
]

SAMPLE_CSV = SAMPLE_CSV_HEADER + "\n" + "\n".join(SAMPLE_CSV_ROWS) + "\n"

# Same data without the OpenInterest column.
SAMPLE_CSV_NO_OI_HEADER = "Date,Open,High,Low,Close,Volume"
SAMPLE_CSV_NO_OI_ROWS = [r.rsplit(",", 1)[0] for r in SAMPLE_CSV_ROWS]
SAMPLE_CSV_NO_OI = (
    SAMPLE_CSV_NO_OI_HEADER + "\n" + "\n".join(SAMPLE_CSV_NO_OI_ROWS) + "\n"
)

NUM_ROWS = len(SAMPLE_CSV_ROWS)


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def sample_csv_text() -> str:
    """Full sample CSV content as a string."""
    return SAMPLE_CSV


@pytest.fixture
def sample_csv_file(tmp_path: Path) -> Path:
    """Write sample CSV to a temporary file and return the path."""
    p = tmp_path / "sample.csv"
    p.write_text(SAMPLE_CSV)
    return p


@pytest.fixture
def sample_csv_no_oi_file(tmp_path: Path) -> Path:
    """Sample CSV without OpenInterest column."""
    p = tmp_path / "sample_no_oi.csv"
    p.write_text(SAMPLE_CSV_NO_OI)
    return p


@pytest.fixture
def sample_csv_io() -> io.StringIO:
    """Sample CSV as a StringIO object (file-like)."""
    return io.StringIO(SAMPLE_CSV)


@pytest.fixture
def sample_dataframe() -> pd.DataFrame:
    """Sample data as a pandas DataFrame with a DatetimeIndex."""
    dates = [
        datetime.strptime(r.split(",")[0], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        for r in SAMPLE_CSV_ROWS
    ]
    data = {
        "Open": [float(r.split(",")[1]) for r in SAMPLE_CSV_ROWS],
        "High": [float(r.split(",")[2]) for r in SAMPLE_CSV_ROWS],
        "Low": [float(r.split(",")[3]) for r in SAMPLE_CSV_ROWS],
        "Close": [float(r.split(",")[4]) for r in SAMPLE_CSV_ROWS],
        "Volume": [float(r.split(",")[5]) for r in SAMPLE_CSV_ROWS],
        "OI": [float(r.split(",")[6]) for r in SAMPLE_CSV_ROWS],
    }
    df = pd.DataFrame(data, index=pd.DatetimeIndex(dates, name="Date"))
    return df


@pytest.fixture
def sample_dataframe_with_date_col() -> pd.DataFrame:
    """Sample data as a DataFrame with Date as a regular column."""
    dates = [
        datetime.strptime(r.split(",")[0], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        for r in SAMPLE_CSV_ROWS
    ]
    data = {
        "Date": dates,
        "Open": [float(r.split(",")[1]) for r in SAMPLE_CSV_ROWS],
        "High": [float(r.split(",")[2]) for r in SAMPLE_CSV_ROWS],
        "Low": [float(r.split(",")[3]) for r in SAMPLE_CSV_ROWS],
        "Close": [float(r.split(",")[4]) for r in SAMPLE_CSV_ROWS],
        "Volume": [float(r.split(",")[5]) for r in SAMPLE_CSV_ROWS],
    }
    return pd.DataFrame(data)
