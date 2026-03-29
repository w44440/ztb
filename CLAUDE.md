# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**ztb-fetcher** is a stock market data aggregation tool that fetches Chinese market limit-up (涨停板) data from two sources:
- **THS (同花顺)** - Using pywencai API
- **JYGS (韭研公社)** - Using Playwright web scraping

The data is stored in DuckDB and exposed via a Typer CLI with commands for fetching, querying, and analyzing data.

## Common Commands

### Environment Setup

```bash
# Install dependencies using uv
uv sync

# Activate virtual environment
source .venv/bin/activate
```

### Running the CLI

```bash
# Direct invocation with uv
uv run ztb --help

# Or via the installed script (after uv sync)
./main.py --help
```

### Main CLI Commands

```bash
# Fetch data for today
uv run ztb fetch

# Fetch data for a specific date
uv run ztb fetch --date 2026-03-29
uv run ztb fetch -d 20260329

# Fetch data for a date range
uv run ztb fetch --start 20260320 --end 20260329

# Query history statistics (last N days)
uv run ztb history --days 7

# Query detailed data
uv run ztb query                    # Summary of all data
uv run ztb query --source ths       # Only THS data
uv run ztb query --source jygs      # Only JYGS data
uv run ztb query --date 20260329 --source ths
```

### Running with Python directly

```bash
# Run main.py directly (Python 3.12 required)
python main.py fetch

# Or with explicit Python interpreter
python3.12 main.py fetch --help
```

## Code Architecture

### Directory Structure

```
ztb_fetcher/
├── __init__.py                 # Package marker
├── calendar.py                 # Trading calendar - trading day validation
├── cli.py                      # Typer CLI with fetch/history/query commands
├── config.py                   # Configuration: paths, API URLs, templates
├── database.py                 # DuckDB abstraction layer
├── fetchers/
│   ├── __init__.py
│   ├── ths_fetcher.py         # THS (同花顺) data fetcher using pywencai
│   └── jygs_fetcher.py        # JYGS (韭研公社) data fetcher using Playwright
└── utils/
    ├── __init__.py
    ├── cache_manager.py       # File-based caching for JYGS data
    ├── error_handler.py       # Custom exception classes
    └── playwright_util.py     # Playwright helpers (CDP mode)
```

### Data Flow Architecture

```
CLI (cli.py)
  ├─→ fetch command
  │    ├─→ TradingCalendar.is_trade_day() [Validate date]
  │    │    ├─→ Query DB if trade date is cached
  │    │    └─→ If not cached, fetch from akshare and cache
  │    │
  │    ├─→ THSFetcher.fetch() (only if trade day)
  │    │    ├─→ pywencai.get() [API call]
  │    │    ├─→ _process_data()
  │    │    └─→ Database.save_zt_stocks()
  │    │         Database.save_zt_reasons()
  │    │
  │    └─→ JYGSFetcher.fetch() (only if THS succeeds)
  │         ├─→ CacheManager.get() [Check cache first]
  │         ├─→ get_data_cdp() [Playwright CDP mode]
  │         │    ├─→ _fetch_single_day()
  │         │    └─→ _extract_data() [DOM parsing]
  │         ├─→ _parse_data()
  │         └─→ Database.save_zt_reasons()
  │
  ├─→ history command
  │    └─→ Database.query_history()
  │
  └─→ query command
       ├─→ Database.query_zt_stocks()
       ├─→ Database.query_zt_reasons()
       └─→ Rich tables for pretty output
```

### Key Classes & Their Responsibilities

**cli.py**
- Typer app with three commands: `fetch`, `history`, `query`
- Handles CLI argument parsing (dates, sources, filters)
- Formats output using Rich tables and console
- Coordinates between fetchers and database

**database.py - Database class**
- Manages DuckDB connection and schema
- Three tables: `zt_stocks` (THS data), `zt_reasons` (reasons from both sources), `fetch_log` (metadata)
- Methods: `save_zt_stocks()`, `save_zt_reasons()`, `query_zt_stocks()`, `query_zt_reasons()`, `query_history()`

**fetchers/ths_fetcher.py - THSFetcher class**
- Uses pywencai library (queries THS API)
- `fetch(date_str)` - Fetch data for a single date
- `fetch_range(start, end)` - Batch fetch multiple dates
- `_process_data()` - Maps THS column names to internal schema
- Returns tuple of (stocks_df, reasons_df)

**fetchers/jygs_fetcher.py - JYGSFetcher class**
- Web scraping using Playwright in CDP (Chrome DevTools Protocol) mode
- `fetch(date_str, filter_codes)` - Fetch with optional code filtering
- `_fetch_single_day()` - Executes in Playwright page context
- `_extract_data()` - DOM parsing to collect stock data from tables
- `_parse_data()` - Converts CSV-like text to DataFrame
- Supports caching via CacheManager

**utils/playwright_util.py**
- `get_data_cdp()` - Main Playwright helper using CDP mode
- Handles browser lifecycle, page context, and custom fetch callbacks
- Supports login checking before data extraction

**calendar.py - TradingCalendar class**
- Validates if a given date is an A-share trading day
- `is_trade_day(date_str)` - Check if date is trading day, auto-caching missing months
- `_fetch_and_cache_month()` - Fetches month trading dates from akshare and caches to DB
- Used in fetch command to skip non-trading days

### Important Design Patterns

1. **Dependency Injection**: Fetchers receive Database instance in constructor
2. **Data Filtering**: JYGS data is filtered by THS codes (see fetch command logic in cli.py)
3. **Caching Strategy**: JYGS uses monthly-subfolder cache to avoid repeated web scrapes
4. **Error Handling**: Custom exception hierarchy (PlaywrightBrowserError, PlaywrightAuthError, etc.)
5. **Schema Mapping**: Both fetchers map source columns to standardized internal schema

### Database Schema

**zt_stocks table** (THS data):
- Primary key: (date, code)
- Fields: code, name, price, change_pct, first_zt_time, lianban_days, zt_type, market_cap, days_ban

**zt_reasons table** (reasons from both sources):
- Primary key: (date, code, source)
- source: 'ths' or 'jygs'
- Fields: cate (category), reason (description)

**fetch_log table** (audit/metadata):
- Tracks when fetches occurred, success/failure status, record counts

**trading_calendar table** (A-share trading days):
- Primary key: trade_date
- Fields: is_open (always TRUE for cached dates), created_at
- Populated by TradingCalendar on-demand when querying dates by month

## Development Notes

- **Python version**: Requires Python 3.12 (specified in pyproject.toml)
- **Package manager**: Uses `uv` for fast dependency resolution
- **Linting**: Configured with Ruff (line-length: 100)
- **Date formats**: Internally uses YYYYMMDD (20260329), displayed as YYYY-MM-DD (2026-03-29)
- **Logging**: basicConfig in cli.py at INFO level; individual modules use module-level loggers
- **CLI framework**: Typer (thin wrapper around Click) with Rich for pretty console output
- **Data processing**: Pandas DataFrames for all data manipulation
- **Web scraping**: Playwright in CDP mode (more robust than standard mode for JYGS)

## Typical Development Workflow

1. **Adding a new command**: Add method to `app` in `cli.py`, use `@app.command()` decorator
2. **Modifying fetch logic**: Edit `THSFetcher._process_data()` or `JYGSFetcher._extract_data()`
3. **Changing database schema**: Modify `Database._init_tables()` in `database.py`
4. **Debugging web scraping**: Check `playwright_util.py` and Playwright browser debugging
5. **Testing changes**: Run `uv run ztb fetch --date YYYYMMDD` with a recent date

## Configuration

All configuration lives in `ztb_fetcher/config.py`:
- `PROJECT_ROOT` - Root directory for data/cache
- `DUCKDB_PATH` - Database file location (data/zt_data.duckdb)
- `LOG_FILE` - Log file location (data/ztb.log)
- `THS_QUERY_TEMPLATE` - pywencai query string
- `JYGS_BASE_URL` - Website base URL
- `JYGS_CACHE_DIR` - Cache directory for JYGS data

## Trading Calendar Feature

The fetch command now validates that the target date is an A-share trading day before attempting to fetch data:

**Behavior**:
- Non-trading days (weekends/holidays) are skipped with a message, not errors
- Trading days proceed normally with data fetching
- Calendar data is fetched from `akshare` library's `tool_trade_date_hist_sina()`
- Results are cached in the `trading_calendar` table to avoid repeated API calls

**Usage**:
```bash
# Trading day - proceeds normally
uv run ztb fetch -d 20260327  # Friday

# Non-trading day - prints message and skips
uv run ztb fetch -d 20260329  # Sunday

# Date range - processes only trading days
uv run ztb fetch --start 20260326 --end 20260330  # Skips weekend
```

**Implementation details** (calendar.py:TradingCalendar):
- First call to check a date triggers akshare query for that month
- Results cached to DB under `trading_calendar` table
- Subsequent checks in same month hit DB cache (no API call)
- Monthly caching via `_month_cache` set prevents duplicate API requests
