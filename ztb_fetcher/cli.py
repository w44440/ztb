"""命令行界面模块

使用 Typer + Rich 构建命令行界面
"""

import json
import logging
from datetime import date, datetime
from typing import Optional

import pandas as pd
import typer
from rich import box
from rich.console import Console
from rich.table import Table

from ztb_fetcher.analysis import generate_report
from ztb_fetcher.calendar import TradingCalendar
from ztb_fetcher.config import LOG_FILE, STATUS_FILE
from ztb_fetcher.database import Database
from ztb_fetcher.fetchers.jygs_fetcher import JYGSFetcher
from ztb_fetcher.fetchers.ths_fetcher import THSFetcher


# 设置日志：同时输出到控制台和文件
def _setup_logging():
    fmt = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    # 配置控制台输出
    logging.basicConfig(level=logging.INFO, format=fmt)
    # 添加文件输出
    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setLevel(logging.INFO)
    fh.setFormatter(logging.Formatter(fmt))
    logging.getLogger().addHandler(fh)


_setup_logging()

app = typer.Typer(help="涨停板数据抓取软件")
console = Console()


def _write_status(
    status: str,
    date_str: str,
    is_trade_day: bool,
    ths_count: int = 0,
    jygs_count: int = 0,
    report: Optional[str] = None,
    warnings: Optional[list] = None,
    error: Optional[str] = None,
) -> None:
    """将运行状态原子写入 last_run.json，供 AI agent 读取判断结果"""
    payload = {
        "status": status,
        "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "date": date_str,
        "is_trade_day": is_trade_day,
        "ths_count": ths_count,
        "jygs_count": jygs_count,
        "report": report,
        "warnings": warnings or [],
        "error": error,
    }
    tmp = STATUS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.rename(STATUS_FILE)


def _parse_date(date_str: str) -> str:
    """解析日期字符串为 YYYYMMDD 格式"""
    # 支持 YYYY-MM-DD 或 YYYYMMDD
    date_str = date_str.replace("-", "")
    if len(date_str) != 8:
        raise ValueError("日期格式应为 YYYYMMDD 或 YYYY-MM-DD")
    return date_str


@app.command()
def fetch(
    date: Optional[str] = typer.Option(
        None, "--date", "-d", help="指定日期 (YYYYMMDD 或 YYYY-MM-DD)"
    ),
    start: Optional[str] = typer.Option(None, "--start", "-s", help="开始日期 (YYYYMMDD)"),
    end: Optional[str] = typer.Option(None, "--end", "-e", help="结束日期 (YYYYMMDD)"),
):
    """抓取涨停数据（先THS，再用THS过滤JYGS）"""
    db = Database()

    # 确定日期范围
    if date:
        date_str = _parse_date(date)
        dates = [date_str]
    elif start and end:
        dates = []
        for d in pd.date_range(start=_parse_date(start), end=_parse_date(end), freq="D"):
            dates.append(d.strftime("%Y%m%d"))
    else:
        # 默认今天
        dates = [datetime.now().strftime("%Y%m%d")]

    console.print(f"[bold blue]开始抓取涨停数据...[/bold blue]")
    console.print(f"日期范围: {dates[0]} 至 {dates[-1]} ({len(dates)} 天)")
    console.print()

    # 初始化交易日历
    calendar = TradingCalendar(db)

    # 状态跟踪，用于写入 last_run.json
    _ths_count = 0
    _jygs_count = 0
    _warnings: list[str] = []
    _ths_error: Optional[str] = None
    _last_trade_date: Optional[str] = None
    _report_path: Optional[str] = None

    try:
        for date_str in dates:
            formatted = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"

            # 校验是否交易日
            if not calendar.is_trade_day(date_str):
                console.print(f"[bold]{formatted}[/bold] [yellow]⊘ 非交易日，跳过[/yellow]")
                continue

            console.print(f"[bold]处理日期: {formatted}[/bold]")

            # Step 1: 先抓取 THS 数据
            ths_codes = set()
            try:
                ths = THSFetcher(db)
                stocks_df, reasons_df = ths.fetch(date_str)
                ths_codes = set(stocks_df["code"].unique()) if not stocks_df.empty else set()
                _ths_count = len(stocks_df)
                _last_trade_date = date_str
                console.print(f"  [green]✓[/green] 同花顺: {len(stocks_df)} 只股票")
            except Exception as e:
                _ths_error = f"同花顺抓取失败: {e}"
                console.print(f"  [red]✗[/red] 同花顺: {e}")
                console.print(f"  [yellow]! 跳过 JYGS（依赖 THS 数据）[/yellow]")
                continue

            # Step 2: 用 THS 股票代码过滤抓取 JYGS
            if ths_codes:
                try:
                    jygs = JYGSFetcher(db)
                    reasons_df = jygs.fetch(date_str, filter_codes=ths_codes)
                    _jygs_count = len(reasons_df)
                    console.print(f"  [green]✓[/green] 韭研公社: {len(reasons_df)} 条原因（过滤后）")
                except Exception as e:
                    _warnings.append(f"韭研公社抓取失败: {e}")
                    console.print(f"  [red]✗[/red] 韭研公社: {e}")
            else:
                console.print(f"  [yellow]! 跳过 JYGS（THS 无数据）[/yellow]")

        console.print()
        console.print("[bold green]✓ 数据抓取完成[/bold green]")

        # 输出统计列表到日志
        stats = []
        for date_str in dates:
            if not calendar.is_trade_day(date_str):
                continue
            # 查询该日期的涨停数量
            date_obj = datetime.strptime(date_str, "%Y%m%d").date()
            stocks_df = db.query_zt_stocks(date_obj)
            count = len(stocks_df)
            formatted_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
            stats.append(f"{formatted_date}: {count}只涨停")

        if stats:
            logging.info("=" * 40)
            logging.info("涨停数据统计")
            for stat in stats:
                logging.info(f"  {stat}")
            logging.info("=" * 40)

        # 生成分析报告（仅最后一个交易日）
        trade_dates = [d for d in dates if calendar.is_trade_day(d)]
        if trade_dates:
            last_date = trade_dates[-1]
            console.print()
            console.print("[bold blue]生成分析报告...[/bold blue]")
            try:
                report_path = generate_report(db, last_date)
                _report_path = str(report_path)
                console.print(f"  [green]✓[/green] {last_date}: {report_path}")
            except Exception as e:
                _warnings.append(f"报告生成失败: {e}")
                console.print(f"  [yellow]! {last_date}: 报告生成失败: {e}[/yellow]")

        # 写入状态文件
        if not trade_dates:
            _write_status("skipped", dates[-1], is_trade_day=False)
        elif _ths_error and _ths_count == 0:
            _write_status("error", _last_trade_date or trade_dates[-1], True,
                          error=_ths_error, warnings=_warnings)
        else:
            _write_status("ok", _last_trade_date or trade_dates[-1], True,
                          _ths_count, _jygs_count, _report_path, _warnings)

    except Exception as e:
        _write_status("error", dates[0] if dates else datetime.now().strftime("%Y%m%d"),
                      True, error=f"未处理的异常: {e}")
        raise


@app.command()
def history(
    days: int = typer.Option(7, "--days", "-d", help="查询天数"),
):
    """查询历史数据统计"""
    db = Database()

    console.print(f"[bold blue]近 {days} 天涨停统计[/bold blue]")
    console.print()

    df = db.query_history(days)

    if df.empty:
        console.print("[yellow]暂无数据[/yellow]")
        return

    table = Table(box=box.SIMPLE)
    table.add_column("日期", style="cyan")
    table.add_column("涨停数量", justify="right", style="green")
    table.add_column("平均连板", justify="right")
    table.add_column("最高连板", justify="right", style="magenta")

    for _, row in df.iterrows():
        table.add_row(
            str(row["date"]),
            str(int(row["count"])),
            f"{row['avg_lianban']:.2f}",
            str(int(row["max_lianban"])),
        )

    console.print(table)


@app.command()
def query(
    date: Optional[str] = typer.Option(None, "--date", "-d", help="指定日期 (YYYYMMDD)"),
    source: Optional[str] = typer.Option(None, "--source", "-s", help="数据源 (ths/jygs)"),
):
    """查询详细数据"""
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

    elif source == "jygs":
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
                str(row["date"]), row["code"], row["name"], row["cate"] or "", row["reason"] or ""
            )

        console.print(table)
        if len(df) > 30:
            console.print(f"[dim]... 还有 {len(df) - 30} 条数据[/dim]")

    else:
        # 显示两个表的统计
        stocks_df = db.query_zt_stocks(date_obj)
        reasons_ths = db.query_zt_reasons(date_obj, source="ths")
        reasons_jygs = db.query_zt_reasons(date_obj, source="jygs")

        console.print(f"[bold]数据统计[/bold]")
        console.print(f"  同花顺涨停股票: {len(stocks_df)} 条")
        console.print(f"  同花顺涨停原因: {len(reasons_ths)} 条")
        console.print(f"  韭研公社涨停原因: {len(reasons_jygs)} 条")


if __name__ == "__main__":
    app()
