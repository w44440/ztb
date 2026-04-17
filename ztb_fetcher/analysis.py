"""涨停分析模块

抓取完成后自动生成分析报告图片（matplotlib）
"""

import re
from collections import Counter
from datetime import datetime
from pathlib import Path

import matplotlib
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager as fm

from ztb_fetcher.config import ANALYSIS_DAYS, REPORTS_DIR

# 尝试加载中文字体（优先 WSL 下的 Windows 字体，手机端首选粗体）
_CHINESE_FONT_CANDIDATES = [
    "/mnt/c/Windows/Fonts/msyhbd.ttc",
    "/mnt/c/Windows/Fonts/msyh.ttc",
    "/mnt/c/Windows/Fonts/simhei.ttf",
    "/mnt/c/Windows/Fonts/NotoSansSC-VF.ttf",
]
for path in _CHINESE_FONT_CANDIDATES:
    if Path(path).exists():
        fm.fontManager.addfont(str(path))
        _prop = fm.FontProperties(fname=str(path))
        plt.rcParams["font.family"] = _prop.get_name()
        plt.rcParams["axes.unicode_minus"] = False
        break

plt.rcParams.update(
    {
        "font.size": 14,
        "font.weight": "bold",
        "axes.titleweight": "bold",
        "axes.labelweight": "bold",
    }
)


def _tokenize_reasons(df: pd.DataFrame, top_n: int = 15) -> pd.DataFrame:
    """轻量分词统计热点关键词"""
    summary_df, _ = build_daily_hot_topics(df, top_n=top_n)
    if summary_df.empty:
        return pd.DataFrame()

    return summary_df[["关键词", "出现次数", "涉及股票数", "样例股票"]]


def build_daily_hot_topics(
    df: pd.DataFrame,
    top_n: int | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """按单日理由数据生成热点汇总和热点-股票明细。"""
    keyword_count = Counter()
    keyword_stocks: dict[str, set[tuple[str, str]]] = {}

    for _, row in df.iterrows():
        tokens = set()
        for field in [row.get("cate", ""), row.get("reason", "")]:
            if not field or pd.isna(field):
                continue
            parts = re.split(r"[+,，、\s/]+", str(field))
            tokens.update(
                p.strip()
                for p in parts
                if p.strip() and len(p.strip()) >= 2 and p.strip() != "其它" and p.strip() != "其他"
            )

        for token in tokens:
            keyword_count[token] += 1
            keyword_stocks.setdefault(token, set()).add((row["code"], row["name"]))

    summary_rows = []
    stock_rows = []
    for rank, (kw, count) in enumerate(keyword_count.most_common(top_n), start=1):
        stocks = sorted(keyword_stocks[kw], key=lambda item: (item[0], item[1]))
        sample = "、".join(name for _, name in stocks[:3])
        summary_rows.append(
            {
                "关键词": kw,
                "出现次数": count,
                "涉及股票数": len(stocks),
                "样例股票": sample,
                "排序": rank,
            }
        )
        for code, name in stocks:
            stock_rows.append({"关键词": kw, "代码": code, "名称": name})

    return pd.DataFrame(summary_rows), pd.DataFrame(stock_rows)


def _format_topic_bar_label(appearance_count: int, stock_count: int) -> str:
    """格式化热点柱状图标签，统一展示计数口径。"""
    return f"{appearance_count}次 / {stock_count}只"


def _plot_report(
    lianban_df: pd.DataFrame,
    trend_df: pd.DataFrame,
    keywords_df: pd.DataFrame,
    date_str: str,
    output_path: Path,
):
    """绘制三张图并保存（针对手机竖屏深度优化）"""
    fig, axes = plt.subplots(3, 1, figsize=(7, 18), gridspec_kw={"height_ratios": [1, 1, 1.6]})
    fig.suptitle(f"涨停分析报告 {date_str}", fontsize=18, fontweight="bold", y=0.95)

    def _fmt_date(d) -> str:
        return d.strftime("%m-%d") if hasattr(d, "strftime") else str(d)[5:10]

    legend_kw = {"loc": "upper center", "bbox_to_anchor": (0.5, -0.18), "ncol": 3, "fontsize": 11}

    # ---------- 子图 1：连板结构 ----------
    ax1 = axes[0]
    if not lianban_df.empty:
        lianban_df = lianban_df.sort_values("date")
        x_labels = [_fmt_date(d) for d in lianban_df["date"]]
        shouban = lianban_df["shouban"].astype(int)
        erban = lianban_df["erban"].astype(int)
        sanban_plus = lianban_df["sanban_plus"].astype(int)

        ax1.bar(x_labels, shouban, label="首板", color="#4CAF50")
        ax1.bar(x_labels, erban, bottom=shouban, label="二板", color="#FFC107")
        ax1.bar(x_labels, sanban_plus, bottom=shouban + erban, label="≥三板", color="#F44336")

        for i, (d, total, max_lb) in enumerate(
            zip(x_labels, lianban_df["total"], lianban_df["max_lianban"])
        ):
            ax1.text(
                i,
                total + 1,
                f"高{int(max_lb)}",
                ha="center",
                va="bottom",
                fontsize=10,
                fontweight="bold",
                color="#1A237E",
            )

        ax1.set_title("连板结构", fontsize=15, pad=10)
        ax1.set_ylabel("涨停数量", fontsize=12)
        ax1.tick_params(axis="both", labelsize=11)
        plt.setp(ax1.xaxis.get_majorticklabels(), rotation=45, ha="right")
        ax1.legend(**legend_kw)
    else:
        ax1.text(0.5, 0.5, "暂无数据", ha="center", va="center", transform=ax1.transAxes)
        ax1.set_title("连板结构", fontsize=15)
        ax1.axis("off")

    # ---------- 子图 2：涨停总数趋势 ----------
    ax2 = axes[1]
    if not trend_df.empty:
        trend_df = trend_df.sort_values("date")
        x_labels = [_fmt_date(d) for d in trend_df["date"]]
        zt_count = trend_df["zt_count"].astype(float)
        ma5 = trend_df["ma5"].astype(float)
        ma10 = trend_df["ma10"].astype(float)

        ax2.plot(
            x_labels,
            zt_count,
            label="涨停数",
            marker="o",
            markersize=8,
            linewidth=3,
            color="#2196F3",
        )
        ax2.plot(
            x_labels,
            ma5,
            label="MA5",
            linestyle="--",
            marker="s",
            markersize=7,
            linewidth=2.5,
            color="#FF9800",
        )
        ax2.plot(
            x_labels,
            ma10,
            label="MA10",
            linestyle=":",
            marker="^",
            markersize=7,
            linewidth=2.5,
            color="#9C27B0",
        )

        latest = trend_df.iloc[-1]
        sentiment_text: str
        sentiment_color: str
        if latest["zt_count"] > latest["ma5"]:
            sentiment_text = "情绪偏暖"
            sentiment_color = "green"
        elif latest["zt_count"] < latest["ma5"] * 0.8:
            sentiment_text = "情绪偏冷"
            sentiment_color = "red"
        else:
            sentiment_text = "情绪中性"
            sentiment_color = "gray"

        ax2.text(
            0.98,
            1.02,
            f"{sentiment_text}",
            transform=ax2.transAxes,
            fontsize=12,
            color=sentiment_color,
            fontweight="bold",
            ha="right",
            va="bottom",
            bbox=dict(boxstyle="round,pad=0.35", facecolor="wheat", alpha=0.6),
        )

        ax2.set_title("涨停总数趋势", fontsize=15, pad=10)
        ax2.set_ylabel("涨停数量", fontsize=12)
        ax2.tick_params(axis="both", labelsize=11)
        plt.setp(ax2.xaxis.get_majorticklabels(), rotation=45, ha="right")
        ax2.legend(**legend_kw)
    else:
        ax2.text(0.5, 0.5, "暂无数据", ha="center", va="center", transform=ax2.transAxes)
        ax2.set_title("涨停总数趋势", fontsize=15)
        ax2.axis("off")

    # ---------- 子图 3：热点理由 Top-N ----------
    ax3 = axes[2]
    if not keywords_df.empty:
        keywords_df = keywords_df.sort_values("出现次数", ascending=True)
        y_labels = keywords_df["关键词"].tolist()
        counts = keywords_df["出现次数"].astype(int)
        colors = plt.cm.RdYlGn(
            [0.2 + 0.6 * i / max(len(y_labels) - 1, 1) for i in range(len(y_labels))]
        )

        bars = ax3.barh(y_labels, counts, color=colors, height=0.55)
        for bar, appearance_count, stock_count in zip(
            bars,
            keywords_df["出现次数"].astype(int),
            keywords_df["涉及股票数"].astype(int),
        ):
            width = bar.get_width()
            ax3.text(
                width + 0.3,
                bar.get_y() + bar.get_height() / 2,
                _format_topic_bar_label(appearance_count, stock_count),
                ha="left",
                va="center",
                fontsize=10,
            )

        ax3.set_title("热点理由 Top", fontsize=15, pad=10)
        ax3.set_xlabel("出现次数", fontsize=12)
        ax3.tick_params(axis="both", labelsize=11)
    else:
        ax3.text(0.5, 0.5, "暂无数据", ha="center", va="center", transform=ax3.transAxes)
        ax3.set_title("热点理由 Top", fontsize=15)
        ax3.axis("off")

    fig.subplots_adjust(left=0.22, top=0.89, hspace=0.55)
    plt.savefig(output_path, dpi=300, pad_inches=0.3)
    plt.close(fig)


def generate_report(db, date_str: str, days: int = ANALYSIS_DAYS) -> Path:
    """生成单日分析报告图片

    Returns:
        图片保存路径
    """
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    output_path = REPORTS_DIR / f"{date_str}.png"

    date_obj = datetime.strptime(date_str, "%Y%m%d").date()

    lianban_df = db.query_lianban_stats(date_val=date_obj, days=days)
    trend_df = db.query_daily_count_with_ma(date_val=date_obj, days=days)
    keywords_df = db.get_hot_topics_by_date(date_obj)
    if not keywords_df.empty:
        keywords_df = keywords_df.rename(
            columns={
                "topic": "关键词",
                "appearance_count": "出现次数",
                "stock_count": "涉及股票数",
                "sample_stocks": "样例股票",
                "rank": "排序",
            }
        )
        keywords_df = keywords_df.sort_values(["排序", "关键词"]).head(10)
    else:
        reasons_df = db.query_zt_reasons(date_obj)
        if not reasons_df.empty:
            keywords_df = _tokenize_reasons(reasons_df, top_n=10)
        else:
            keywords_df = pd.DataFrame()

    _plot_report(lianban_df, trend_df, keywords_df, date_str, output_path)
    return output_path
