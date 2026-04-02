# CLAUDE.md

本文件用于指导 Claude Code 在本仓库协作，信息保持精简。

## 项目概览
`ztb-fetcher` 抓取 A 股涨停板数据：THS 通过 pywencai，JYGS 通过 Playwright CDP+缓存，结果写入 DuckDB，Typer CLI 暴露 `fetch`、`history`、`query` 命令。

## 快速命令
```bash
uv sync
source .venv/bin/activate
uv run ztb --help
uv run ztb fetch
uv run ztb fetch --date 20260329
uv run ztb query --source ths
```

## 目录速览
```
ztb_fetcher/
├── cli.py            # Typer CLI
├── calendar.py       # 交易日校验与缓存
├── config.py         # 路径、API、模板
├── database.py       # DuckDB 封装
├── fetchers/
│   ├── ths_fetcher.py   # pywencai
│   └── jygs_fetcher.py  # Playwright+缓存
└── utils/
    ├── cache_manager.py
    ├── error_handler.py
    └── playwright_util.py
```

## 数据流程（摘要）
1. `fetch`: 校验交易日 -> THS 入库 -> JYGS 视缓存补理由。
2. `history`: `Database.query_history()` 汇总最近 N 日数据。
3. `query`: `Database.query_zt_stocks/zt_reasons()`，以 Rich 表格输出。

## 模块要点
- `cli.py`: 解析命令、组织输出、调度 fetcher 与数据库。
- `database.py`: 维护 `zt_stocks`、`zt_reasons`、`fetch_log` 三表及写/查接口。
- `fetchers/ths_fetcher.py`: pywencai 拉取并映射字段。
- `fetchers/jygs_fetcher.py`: CDP 抓取+缓存，解析 DOM/CSV。
- `calendar.py`: 按月缓存交易日，供抓取前快速校验。
