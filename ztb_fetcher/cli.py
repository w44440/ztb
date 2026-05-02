"""命令行界面模块."""

import json
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping, Optional

import pandas as pd
import typer
from rich import box
from rich.console import Console
from rich.table import Table
from web_state_store import (
    StateStoreError,
    capture_state,
    check_state,
    download_state,
    get_state_path,
    upload_state,
)

from ztb_fetcher.analysis import _tokenize_reasons, build_daily_hot_topics, generate_report
from ztb_fetcher.calendar import TradingCalendar
from ztb_fetcher.config import JYGS_LOGIN_URL, LOG_FILE, STATUS_FILE, get_config
from ztb_fetcher.database import Database
from ztb_fetcher.fetchers.jygs_fetcher import JYGSFetcher
from ztb_fetcher.fetchers.ths_fetcher import THSFetcher
from ztb_fetcher.notifier import notify_fetch_result


def _setup_logging():
    fmt = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    logging.basicConfig(level=logging.INFO, format=fmt)
    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setLevel(logging.INFO)
    fh.setFormatter(logging.Formatter(fmt))
    logging.getLogger().addHandler(fh)


_setup_logging()

app = typer.Typer(help="涨停板数据抓取软件")
agent_app = typer.Typer(help="面向 agent 的结构化命令")
auth_app = typer.Typer(help="网站登录态同步命令")
app.add_typer(agent_app, name="agent")
app.add_typer(auth_app, name="auth")
console = Console()


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, pd.DataFrame):
        return value.to_dict(orient="records")
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _print_json(payload: Mapping[str, Any]) -> None:
    console.print(json.dumps(payload, ensure_ascii=False, default=_json_default))


def _parse_date(date_str: str) -> str:
    date_str = date_str.replace("-", "")
    if len(date_str) != 8:
        raise ValueError("日期格式应为 YYYYMMDD 或 YYYY-MM-DD")
    return date_str


def _resolve_dates(
    date_value: Optional[str],
    start_value: Optional[str],
    end_value: Optional[str],
) -> list[str]:
    if date_value:
        return [_parse_date(date_value)]
    if start_value and end_value:
        return [
            d.strftime("%Y%m%d")
            for d in pd.date_range(
                start=_parse_date(start_value), end=_parse_date(end_value), freq="D"
            )
        ]
    return [datetime.now().strftime("%Y%m%d")]


def _status_from_results(results: list[dict[str, Any]]) -> str:
    trade_results = [item for item in results if item["is_trade_day"]]
    if not trade_results:
        return "skipped"
    if any(item["status"] == "error" for item in trade_results):
        return "error"
    if any(item["status"] == "partial" for item in trade_results):
        return "partial"
    return "ok"


def _date_to_obj(date_str: str) -> date:
    return datetime.strptime(date_str, "%Y%m%d").date()


def _get_existing_ths_codes(db: Database, date_str: str) -> set[str]:
    stocks_df = db.query_zt_stocks(_date_to_obj(date_str))
    if stocks_df.empty:
        return set()
    return set(stocks_df["code"].astype(str).unique())


def _run_single_fetch(
    db: Database,
    calendar: TradingCalendar,
    date_str: str,
    source: str,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "date": date_str,
        "is_trade_day": False,
        "status": "skipped",
        "ths": {
            "requested": source in {"all", "ths"},
            "status": "skipped",
            "count": 0,
            "error": None,
        },
        "jygs": {
            "requested": source in {"all", "jygs"},
            "status": "skipped",
            "count": 0,
            "error": None,
        },
        "warnings": [],
        "error": None,
    }

    if not calendar.is_trade_day(date_str):
        return result

    result["is_trade_day"] = True
    result["status"] = "ok"

    ths_codes: set[str] = set()
    if source in {"all", "ths"}:
        try:
            ths = THSFetcher(db)
            stocks_df, _ = ths.fetch(date_str)
            ths_codes = (
                set(stocks_df["code"].astype(str).unique()) if not stocks_df.empty else set()
            )
            ths_metadata = ths.last_fetch_metadata
            result["ths"] = {
                "requested": True,
                "status": "ok",
                "count": len(stocks_df),
                "error": None,
                "cate_count": int(ths_metadata.get("cate_count", 0)),
            }
            result["warnings"].extend(str(item) for item in ths_metadata.get("warnings", []))
            if result["warnings"] and result["status"] == "ok":
                result["status"] = "partial"
        except Exception as exc:  # noqa: BLE001 - surfaced in structured result.
            error_message = f"同花顺抓取失败: {exc}"
            result["ths"] = {
                "requested": True,
                "status": "error",
                "count": 0,
                "error": error_message,
                "cate_count": 0,
            }
            result["status"] = "error"
            result["error"] = error_message
            return result
    else:
        ths_codes = _get_existing_ths_codes(db, date_str)
        result["ths"] = {
            "requested": False,
            "status": "cached" if ths_codes else "missing",
            "count": len(ths_codes),
            "error": None,
            "cate_count": 0,
        }

    if source in {"all", "jygs"}:
        if not ths_codes:
            if source == "jygs":
                error_message = "韭研公社单独抓取依赖现有 THS 数据作为过滤条件"
                result["jygs"] = {
                    "requested": True,
                    "status": "error",
                    "count": 0,
                    "error": error_message,
                }
                result["status"] = "error"
                result["error"] = error_message
                return result

            result["jygs"] = {
                "requested": True,
                "status": "skipped",
                "count": 0,
                "error": "THS 无数据，跳过 JYGS",
            }
        else:
            try:
                jygs = JYGSFetcher(db)
                reasons_df = jygs.fetch(date_str, filter_codes=ths_codes)
                if reasons_df.empty:
                    warning_message = "韭研公社未抓取到数据，可能未登录，请先运行 `ztb login`"
                    result["jygs"] = {
                        "requested": True,
                        "status": "error",
                        "count": 0,
                        "error": warning_message,
                    }
                    result["warnings"].append(warning_message)
                    result["status"] = "partial"
                else:
                    result["jygs"] = {
                        "requested": True,
                        "status": "ok",
                        "count": len(reasons_df),
                        "error": None,
                    }
            except Exception as exc:  # noqa: BLE001 - surfaced in structured result.
                warning_message = f"韭研公社抓取失败: {exc}"
                result["jygs"] = {
                    "requested": True,
                    "status": "error",
                    "count": 0,
                    "error": warning_message,
                }
                result["warnings"].append(warning_message)
                result["status"] = "partial"

    try:
        _refresh_daily_hot_topics(db, date_str)
    except Exception as exc:  # noqa: BLE001 - surfaced as warning.
        warning_message = f"热点回顾生成失败: {exc}"
        result["warnings"].append(warning_message)
        if result["status"] == "ok":
            result["status"] = "partial"

    return result


def _run_fetch_command(
    db: Database,
    dates: list[str],
    source: str = "all",
) -> dict[str, Any]:
    calendar = TradingCalendar(db)
    results = [_run_single_fetch(db, calendar, date_str, source) for date_str in dates]
    trade_results = [item for item in results if item["is_trade_day"]]
    latest_trade_result = trade_results[-1] if trade_results else None
    return {
        "command": "fetch",
        "status": _status_from_results(results),
        "source": source,
        "dates": dates,
        "results": results,
        "latest_trade_date": latest_trade_result["date"] if latest_trade_result else None,
        "summary": {
            "requested_days": len(dates),
            "trade_days": len(trade_results),
            "ths_count": sum(
                item["ths"]["count"] for item in trade_results if item["ths"]["requested"]
            ),
            "jygs_count": sum(
                item["jygs"]["count"] for item in trade_results if item["jygs"]["requested"]
            ),
        },
    }


def _sentiment_label(trend_df: pd.DataFrame) -> str:
    if trend_df.empty:
        return "暂无数据"
    latest = trend_df.sort_values("date").iloc[-1]
    if latest["zt_count"] > latest["ma5"]:
        return "情绪偏暖"
    if latest["zt_count"] < latest["ma5"] * 0.8:
        return "情绪偏冷"
    return "情绪中性"


def _build_context_payload(db: Database, date_str: str, days: int) -> dict[str, Any]:
    date_obj = _date_to_obj(date_str)
    lianban_df = db.query_lianban_stats(date_val=date_obj, days=days)
    trend_df = db.query_daily_count_with_ma(date_val=date_obj, days=days)
    stocks_df = db.query_zt_stocks(date_obj)
    fetch_logs_df = db.query_fetch_logs(date_obj)
    topic_df = _get_hot_topics_for_window(db, date_obj, days)

    latest_lianban = lianban_df.sort_values("date").iloc[-1] if not lianban_df.empty else None
    leaders = []
    if not stocks_df.empty:
        leader_df = stocks_df.sort_values(
            by=["lianban_days", "change_pct", "market_cap"],
            ascending=[False, False, False],
            na_position="last",
        ).head(10)
        leaders = leader_df[
            ["code", "name", "lianban_days", "zt_type", "first_zt_time", "change_pct"]
        ].to_dict(orient="records")

    data_quality = {
        "ths_status": "missing",
        "jygs_status": "missing",
        "is_trade_day": None,
        "warnings": [],
    }
    if not fetch_logs_df.empty:
        source_logs = fetch_logs_df.sort_values("created_at").groupby("source").tail(1)
        for _, row in source_logs.iterrows():
            status_key = f"{row['source']}_status"
            data_quality[status_key] = row["status"]
            if row["message"]:
                data_quality["warnings"].append(str(row["message"]))

    trade_day = TradingCalendar(db).is_trade_day(date_str)
    data_quality["is_trade_day"] = trade_day
    if stocks_df.empty:
        data_quality["warnings"].append("当日无 THS 涨停数据")
    if db.query_zt_reasons(date_obj, source="jygs").empty:
        data_quality["warnings"].append("当日无 JYGS 涨停原因数据")

    summary = {
        "zt_count": len(stocks_df),
        "max_lianban": int(latest_lianban["max_lianban"]) if latest_lianban is not None else 0,
        "avg_lianban": float(latest_lianban["avg_lianban"]) if latest_lianban is not None else 0.0,
        "sentiment_label": _sentiment_label(trend_df),
    }
    lianban_breakdown = {
        "shouban": int(latest_lianban["shouban"]) if latest_lianban is not None else 0,
        "erban": int(latest_lianban["erban"]) if latest_lianban is not None else 0,
        "sanban_plus": int(latest_lianban["sanban_plus"]) if latest_lianban is not None else 0,
    }

    return {
        "command": "context",
        "status": "ok",
        "market_date": date_str,
        "summary": summary,
        "lianban_breakdown": lianban_breakdown,
        "trend": trend_df.sort_values("date").to_dict(orient="records"),
        "hot_topics": topic_df.to_dict(orient="records"),
        "leaders": leaders,
        "data_quality": data_quality,
    }


def _build_fetch_status_payload(
    fetch_result: dict[str, Any],
    report_path: Optional[str] = None,
    report_error: Optional[str] = None,
    notify_warnings: Optional[list[str]] = None,
) -> dict[str, Any]:
    trade_results = [item for item in fetch_result["results"] if item["is_trade_day"]]
    if not trade_results:
        date_str = fetch_result["dates"][-1]
        return {
            "status": "skipped",
            "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "date": date_str,
            "is_trade_day": False,
            "ths_count": 0,
            "jygs_count": 0,
            "report": None,
            "warnings": [],
            "error": None,
            "failed_stage": None,
            "sources": {},
        }

    latest = trade_results[-1]
    warnings = list(latest["warnings"])
    if report_error:
        warnings.append(report_error)
    if notify_warnings:
        warnings.extend(notify_warnings)

    status = latest["status"]
    failed_stage = None
    error = latest["error"]
    if latest["ths"]["status"] == "error":
        failed_stage = "ths"
    elif latest["jygs"]["status"] == "error":
        failed_stage = "jygs"
    elif report_error:
        failed_stage = "report"
    elif notify_warnings:
        failed_stage = "notify"

    if status == "ok" and warnings:
        status = "partial"

    return {
        "status": status,
        "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "date": latest["date"],
        "is_trade_day": True,
        "ths_count": latest["ths"]["count"],
        "jygs_count": latest["jygs"]["count"],
        "report": report_path,
        "warnings": warnings,
        "error": error,
        "failed_stage": failed_stage,
        "sources": {
            "ths": latest["ths"],
            "jygs": latest["jygs"],
            "report": {
                "requested": True,
                "status": "error" if report_error else ("ok" if report_path else "skipped"),
                "path": report_path,
                "error": report_error,
            },
            "notify": {
                "requested": True,
                "status": "warning" if notify_warnings else "ok",
                "error": "; ".join(notify_warnings or []),
            },
        },
    }


def _write_status(payload: dict[str, Any]) -> None:
    tmp = STATUS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.rename(STATUS_FILE)


def _refresh_daily_hot_topics(db: Database, date_str: str) -> None:
    date_obj = _date_to_obj(date_str)
    reasons_df = db.query_zt_reasons(date_obj)
    summary_df, stock_df = build_daily_hot_topics(reasons_df)

    if summary_df.empty:
        normalized_summary = pd.DataFrame(
            columns=["date", "topic", "appearance_count", "stock_count", "sample_stocks", "rank"]
        )
    else:
        normalized_summary = summary_df.rename(
            columns={
                "关键词": "topic",
                "出现次数": "appearance_count",
                "涉及股票数": "stock_count",
                "样例股票": "sample_stocks",
                "排序": "rank",
            }
        )
        normalized_summary["date"] = date_obj
        normalized_summary = normalized_summary[
            ["date", "topic", "appearance_count", "stock_count", "sample_stocks", "rank"]
        ]

    if stock_df.empty:
        normalized_stock_df = pd.DataFrame(columns=["date", "topic", "code", "name"])
    else:
        normalized_stock_df = stock_df.rename(
            columns={"关键词": "topic", "代码": "code", "名称": "name"}
        )
        normalized_stock_df["date"] = date_obj
        normalized_stock_df = normalized_stock_df[["date", "topic", "code", "name"]]

    db.save_daily_hot_topics(date_obj, normalized_summary, normalized_stock_df)


def _format_stock_names(stocks_df: pd.DataFrame, limit: int = 5) -> str:
    if stocks_df.empty:
        return "-"

    names = stocks_df["name"].astype(str).tolist()
    text = "、".join(names[:limit])
    if len(names) > limit:
        return f"{text} 等{len(names)}只"
    return text


def _get_hot_topics_for_window(db: Database, date_obj: date, days: int) -> pd.DataFrame:
    min_date = pd.Timestamp(date_obj) - pd.Timedelta(days=days - 1)
    topic_df = db.get_hot_topics_in_range(min_date.date(), date_obj)
    if not topic_df.empty:
        return topic_df.rename(
            columns={
                "topic": "关键词",
                "appearance_count": "出现次数",
                "stock_count": "涉及股票数",
                "sample_stocks": "样例股票",
                "rank": "排序",
            }
        )

    reasons_df = db.query_zt_reasons()
    if reasons_df.empty:
        return pd.DataFrame()

    reasons_df = reasons_df[reasons_df["date"] >= min_date]
    return _tokenize_reasons(reasons_df, top_n=10)


@app.command()
def fetch(
    date: Optional[str] = typer.Option(
        None, "--date", "-d", help="指定日期 (YYYYMMDD 或 YYYY-MM-DD)"
    ),
    start: Optional[str] = typer.Option(None, "--start", "-s", help="开始日期 (YYYYMMDD)"),
    end: Optional[str] = typer.Option(None, "--end", "-e", help="结束日期 (YYYYMMDD)"),
):
    """抓取涨停数据并生成报告、推送企业微信."""
    db = Database()
    dates = _resolve_dates(date, start, end)

    console.print("[bold blue]开始抓取涨停数据...[/bold blue]")
    console.print(f"日期范围: {dates[0]} 至 {dates[-1]} ({len(dates)} 天)")
    console.print()

    fetch_result = _run_fetch_command(db, dates, source="all")
    for item in fetch_result["results"]:
        formatted = f"{item['date'][:4]}-{item['date'][4:6]}-{item['date'][6:8]}"
        if not item["is_trade_day"]:
            console.print(f"[bold]{formatted}[/bold] [yellow]⊘ 非交易日，跳过[/yellow]")
            continue

        console.print(f"[bold]处理日期: {formatted}[/bold]")
        if item["ths"]["status"] == "ok":
            console.print(f"  [green]✓[/green] 同花顺: {item['ths']['count']} 只股票")
        else:
            console.print(f"  [red]✗[/red] 同花顺: {item['ths']['error']}")
            console.print("  [yellow]! 跳过 JYGS（依赖 THS 数据）[/yellow]")
            continue

        if item["jygs"]["status"] == "ok":
            console.print(f"  [green]✓[/green] 韭研公社: {item['jygs']['count']} 条原因（过滤后）")
        elif item["jygs"]["status"] == "error":
            console.print(f"  [red]✗[/red] 韭研公社: {item['jygs']['error']}")
        elif item["jygs"]["status"] == "skipped":
            console.print("  [yellow]! 跳过 JYGS（THS 无数据）[/yellow]")

    console.print()
    console.print("[bold green]✓ 数据抓取完成[/bold green]")

    report_path = None
    report_error = None
    latest_trade_result = next(
        (
            item
            for item in reversed(fetch_result["results"])
            if item["is_trade_day"] and item["status"] != "error"
        ),
        None,
    )
    if latest_trade_result:
        console.print()
        console.print("[bold blue]生成分析报告...[/bold blue]")
        try:
            output_path = generate_report(db, latest_trade_result["date"])
            report_path = str(output_path)
            console.print(f"  [green]✓[/green] {latest_trade_result['date']}: {output_path}")
        except Exception as exc:  # noqa: BLE001 - reported via status file.
            report_error = f"报告生成失败: {exc}"
            console.print(f"  [yellow]! {latest_trade_result['date']}: {report_error}[/yellow]")

    console.print()
    console.print("[bold blue]推送企业微信...[/bold blue]")

    status_payload = _build_fetch_status_payload(fetch_result, report_path, report_error)
    notify_warnings = notify_fetch_result(status_payload)
    status_payload = _build_fetch_status_payload(
        fetch_result,
        report_path=report_path,
        report_error=report_error,
        notify_warnings=notify_warnings,
    )
    _write_status(status_payload)

    if notify_warnings:
        console.print(f"  [yellow]! {'; '.join(notify_warnings)}[/yellow]")
    else:
        console.print("  [green]✓[/green] 企业微信推送完成")

    if status_payload["status"] == "error":
        raise typer.Exit(code=1)


@app.command()
def history(topic: Optional[str] = typer.Option(None, "--topic", "-p", help="指定热点词")):
    """查询当日最热热点回顾."""
    db = Database()
    latest_date = db.get_latest_hot_topic_date()
    if latest_date is None:
        console.print("[yellow]暂无热点回顾数据[/yellow]")
        return

    notice = None
    if topic:
        current_df = db.get_hot_topic_by_date(latest_date, topic)
        if current_df.empty:
            current_df = db.get_latest_hot_topic_occurrence(topic, latest_date)
            if current_df.empty:
                console.print(f"[yellow]热点 {topic} 暂无历史记录[/yellow]")
                return
            notice = f"热点 {topic} 当日未出现，展示最近一次历史记录"
    else:
        current_df = db.get_hot_topics_by_date(latest_date).head(1)
        if current_df.empty:
            console.print("[yellow]暂无热点回顾数据[/yellow]")
            return
        topic = str(current_df.iloc[0]["topic"])

    current_row = current_df.iloc[0]
    current_date = pd.Timestamp(current_row["date"]).date()
    previous_df = db.get_previous_hot_topic_occurrence(topic, current_date)
    current_stocks_df = db.get_hot_topic_stocks(current_date, topic)
    previous_stocks_df = (
        db.get_hot_topic_stocks(pd.Timestamp(previous_df.iloc[0]["date"]).date(), topic)
        if not previous_df.empty
        else pd.DataFrame()
    )

    console.print("[bold blue]热点回顾[/bold blue]")
    if notice:
        console.print(f"[yellow]{notice}[/yellow]")
    console.print()

    table = Table(box=box.SIMPLE)
    table.add_column("字段", style="cyan")
    table.add_column("内容")
    table.add_row("日期", str(current_date))
    table.add_row("热点", str(topic))
    table.add_row("当日出现次数", str(int(current_row["appearance_count"])))
    table.add_row("当日涉及股票数", str(int(current_row["stock_count"])))
    table.add_row("当日涨停股票", _format_stock_names(current_stocks_df))

    if previous_df.empty:
        table.add_row("上次出现日期", "首次出现")
        table.add_row("上次涨停股票", "-")
    else:
        previous_date = pd.Timestamp(previous_df.iloc[0]["date"]).date()
        table.add_row("上次出现日期", str(previous_date))
        table.add_row("上次涨停股票", _format_stock_names(previous_stocks_df))

    console.print(table)


@app.command("backfill-topics")
def backfill_topics():
    """基于本地理由数据回填每日热点结果."""
    db = Database()
    reason_dates = db.get_reason_dates()
    if not reason_dates:
        console.print("[yellow]暂无理由数据，无需回填[/yellow]")
        return

    console.print("[bold blue]开始回填每日热点...[/bold blue]")
    success_count = 0
    failed_dates: list[str] = []

    for date_obj in reason_dates:
        date_str = date_obj.strftime("%Y%m%d")
        try:
            _refresh_daily_hot_topics(db, date_str)
            success_count += 1
        except Exception as exc:  # noqa: BLE001 - surfaced in CLI summary.
            failed_dates.append(f"{date_str}: {exc}")

    console.print(f"[green]✓ 已处理 {success_count}/{len(reason_dates)} 天[/green]")
    if failed_dates:
        console.print("[yellow]以下日期回填失败:[/yellow]")
        for item in failed_dates:
            console.print(f"  {item}")
        raise typer.Exit(code=1)


@app.command()
def query(
    date: Optional[str] = typer.Option(None, "--date", "-d", help="指定日期 (YYYYMMDD)"),
    source: Optional[str] = typer.Option(None, "--source", "-s", help="数据源 (ths/jygs)"),
):
    """查询详细数据."""
    db = Database()

    date_obj = None
    if date:
        date_obj = datetime.strptime(_parse_date(date), "%Y%m%d").date()

    if source == "ths":
        df = db.query_zt_stocks(date_obj)
        if df.empty:
            console.print("[yellow]暂无同花顺数据[/yellow]")
            return

        table = Table(box=box.SIMPLE, title=f"同花顺涨停数据 ({date or '全部'})")
        table.add_column("日期", style="cyan")
        table.add_column("代码", style="blue")
        table.add_column("名称")
        table.add_column("最新价", justify="right")
        table.add_column("涨跌幅", justify="right")
        table.add_column("首次涨停", justify="right")
        table.add_column("连板", justify="right", style="magenta")
        table.add_column("涨停类型")

        for _, row in df.head(30).iterrows():
            table.add_row(
                str(row["date"]),
                row["code"],
                row["name"],
                str(row["price"]),
                f"{row['change_pct']}%" if pd.notna(row["change_pct"]) else "",
                row["first_zt_time"] or "",
                str(row["lianban_days"]) if pd.notna(row["lianban_days"]) else "",
                row["zt_type"] or "",
            )

        console.print(table)
        if len(df) > 30:
            console.print(f"[dim]... 还有 {len(df) - 30} 条数据[/dim]")
        return

    if source == "jygs":
        df = db.query_zt_reasons(date_obj, source="jygs")
        if df.empty:
            console.print("[yellow]暂无韭研公社数据[/yellow]")
            return

        table = Table(box=box.SIMPLE, title=f"韭研公社涨停原因 ({date or '全部'})")
        table.add_column("日期", style="cyan")
        table.add_column("代码", style="blue")
        table.add_column("名称")
        table.add_column("分类", style="green")
        table.add_column("原因")

        for _, row in df.head(30).iterrows():
            table.add_row(
                str(row["date"]),
                row["code"],
                row["name"],
                row["cate"] or "",
                row["reason"] or "",
            )

        console.print(table)
        if len(df) > 30:
            console.print(f"[dim]... 还有 {len(df) - 30} 条数据[/dim]")
        return

    stocks_df = db.query_zt_stocks(date_obj)
    reasons_ths = db.query_zt_reasons(date_obj, source="ths")
    reasons_jygs = db.query_zt_reasons(date_obj, source="jygs")

    console.print("[bold]数据统计[/bold]")
    console.print(f"  同花顺涨停股票: {len(stocks_df)} 条")
    console.print(f"  同花顺涨停原因: {len(reasons_ths)} 条")
    console.print(f"  韭研公社涨停原因: {len(reasons_jygs)} 条")


def _login_jygs(timeout: int = 600) -> None:
    """打开浏览器完成韭研公社登录并保存 storage_state。"""
    login_url = get_config("jygs_login_url", JYGS_LOGIN_URL)
    state_path = get_state_path()

    console.print("[bold blue]准备登录韭研公社...[/bold blue]")
    console.print(f"登录页: {login_url}")
    console.print(f"状态文件: {state_path}")

    try:
        capture_state(
            "jygs",
            path=state_path,
            login_timeout_seconds=timeout,
            check_login_func=JYGSFetcher._check_login,
        )
    except Exception as exc:  # noqa: BLE001 - surfaced in CLI output.
        console.print(f"[red]✗ 登录失败: {exc}[/red]")
        raise typer.Exit(code=1)

    console.print("[bold green]✓ 登录状态文件已保存[/bold green]")


@app.command("login")
def login(
    timeout: int = typer.Option(600, "--timeout", help="等待手动登录的超时时间（秒）"),
):
    """打开浏览器完成登录并保存状态."""
    _login_jygs(timeout=timeout)


@auth_app.command("upload-jygs-state")
def auth_upload_jygs_state():
    """校验并上传 JYGS 登录态文件到对象存储."""
    try:
        upload_state("jygs")
    except StateStoreError as exc:
        console.print(f"[red]✗ 上传失败: {exc}[/red]")
        raise typer.Exit(code=1)
    console.print(f"[bold green]✓ 已上传 JYGS 状态文件: {get_state_path()}[/bold green]")


@auth_app.command("download-jygs-state")
def auth_download_jygs_state():
    """从对象存储下载并校验 JYGS 登录态文件."""
    try:
        path = download_state("jygs")
        check_state("jygs", path=path)
    except StateStoreError as exc:
        console.print(f"[red]✗ 下载或校验失败: {exc}[/red]")
        raise typer.Exit(code=1)
    console.print(f"[bold green]✓ 已下载并校验 JYGS 状态文件: {path}[/bold green]")


@auth_app.command("check-jygs-state")
def auth_check_jygs_state():
    """校验本地 JYGS 登录态文件是否有效."""
    try:
        check_state("jygs")
    except StateStoreError as exc:
        console.print(f"[red]✗ 状态文件无效: {exc}[/red]")
        raise typer.Exit(code=1)
    console.print(f"[bold green]✓ JYGS 状态文件有效: {get_state_path()}[/bold green]")


@agent_app.command("fetch")
def agent_fetch(
    date: Optional[str] = typer.Option(
        None, "--date", "-d", help="指定日期 (YYYYMMDD 或 YYYY-MM-DD)"
    ),
    start: Optional[str] = typer.Option(None, "--start", "-s", help="开始日期 (YYYYMMDD)"),
    end: Optional[str] = typer.Option(None, "--end", "-e", help="结束日期 (YYYYMMDD)"),
    source: str = typer.Option("all", "--source", help="抓取来源: all/ths/jygs"),
):
    """只抓取和入库，默认结构化 JSON 输出."""
    if source not in {"all", "ths", "jygs"}:
        raise typer.BadParameter("source 仅支持 all/ths/jygs")

    db = Database()
    payload = _run_fetch_command(db, _resolve_dates(date, start, end), source=source)
    payload["command"] = "agent.fetch"
    _print_json(payload)
    raise typer.Exit(code=1 if payload["status"] == "error" else 0)


@agent_app.command("context")
def agent_context(
    date: str = typer.Option(..., "--date", "-d", help="指定日期 (YYYYMMDD 或 YYYY-MM-DD)"),
    days: int = typer.Option(5, "--days", help="分析窗口天数"),
):
    """输出给 agent/LLM 使用的结构化上下文."""
    db = Database()
    payload = _build_context_payload(db, _parse_date(date), days=days)
    payload["command"] = "agent.context"
    _print_json(payload)


@agent_app.command("report")
def agent_report(
    date: str = typer.Option(..., "--date", "-d", help="指定日期 (YYYYMMDD 或 YYYY-MM-DD)"),
    days: int = typer.Option(5, "--days", help="分析窗口天数"),
):
    """单独生成报告图片."""
    db = Database()
    date_str = _parse_date(date)
    try:
        path = generate_report(db, date_str, days=days)
    except Exception as exc:  # noqa: BLE001 - converted into structured CLI output.
        _print_json(
            {
                "command": "agent.report",
                "status": "error",
                "date": date_str,
                "report": None,
                "error": str(exc),
            }
        )
        raise typer.Exit(code=1)

    _print_json(
        {
            "command": "agent.report",
            "status": "ok",
            "date": date_str,
            "report": str(path),
            "error": None,
        }
    )


@agent_app.command("notify")
def agent_notify(
    date: str = typer.Option(..., "--date", "-d", help="指定日期 (YYYYMMDD 或 YYYY-MM-DD)"),
    report: Optional[str] = typer.Option(None, "--report", help="指定报告图片路径"),
):
    """单独推送企业微信通知."""
    date_str = _parse_date(date)
    payload = {
        "status": "ok",
        "date": date_str,
        "is_trade_day": True,
        "ths_count": 0,
        "jygs_count": 0,
        "report": report,
        "warnings": [],
        "error": None,
    }
    warnings = notify_fetch_result(payload)
    response = {
        "command": "agent.notify",
        "status": "partial" if warnings else "ok",
        "date": date_str,
        "report": report,
        "warnings": warnings,
        "error": None,
    }
    _print_json(response)
    if warnings:
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
