"""DuckDB 数据库操作模块"""

from datetime import date
from pathlib import Path
from typing import Optional

import duckdb
import pandas as pd

from ztb_fetcher.config import DUCKDB_PATH


class Database:
    """DuckDB 数据库管理类"""

    def __init__(self, db_path: Path = DUCKDB_PATH):
        self.db_path = db_path
        self._init_tables()

    def _get_connection(self) -> duckdb.DuckDBPyConnection:
        """获取数据库连接"""
        return duckdb.connect(str(self.db_path))

    def _init_tables(self):
        """初始化数据库表结构"""
        conn = self._get_connection()

        # zt_stocks 表 - 涨停股票基础数据（同花顺）
        conn.execute("""
            CREATE TABLE IF NOT EXISTS zt_stocks (
                date DATE NOT NULL,
                code VARCHAR NOT NULL,
                name VARCHAR NOT NULL,
                price DECIMAL(10,2),
                change_pct DECIMAL(10,2),
                first_zt_time VARCHAR,
                lianban_days INTEGER,
                zt_type VARCHAR,
                market_cap DECIMAL(20,2),
                days_ban VARCHAR,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (date, code)
            )
        """)

        # zt_reasons 表 - 涨停原因（同花顺 + 韭研公社）
        conn.execute("""
            CREATE TABLE IF NOT EXISTS zt_reasons (
                date DATE NOT NULL,
                code VARCHAR NOT NULL,
                name VARCHAR NOT NULL,
                source VARCHAR NOT NULL,
                cate VARCHAR,
                reason VARCHAR,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (date, code, source)
            )
        """)

        # fetch_log 表 - 抓取日志
        conn.execute("""
            CREATE TABLE IF NOT EXISTS fetch_log (
                date DATE NOT NULL,
                source VARCHAR NOT NULL,
                count INTEGER,
                status VARCHAR,
                message VARCHAR,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # trading_calendar 表 - 交易日日历
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trading_calendar (
                trade_date DATE NOT NULL,
                is_open BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (trade_date)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS daily_hot_topics (
                date DATE NOT NULL,
                topic VARCHAR NOT NULL,
                appearance_count INTEGER NOT NULL,
                stock_count INTEGER NOT NULL,
                sample_stocks VARCHAR,
                rank INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (date, topic)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS daily_hot_topic_stocks (
                date DATE NOT NULL,
                topic VARCHAR NOT NULL,
                code VARCHAR NOT NULL,
                name VARCHAR NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (date, topic, code)
            )
        """)

        conn.close()

    def save_zt_stocks(self, df: pd.DataFrame):
        """保存涨停股票基础数据"""
        if df.empty:
            return

        conn = self._get_connection()
        try:
            # 清空该日期的旧数据
            dates = df["date"].unique().tolist()
            for d in dates:
                conn.execute("DELETE FROM zt_stocks WHERE date = ?", [d])

            # 插入新数据
            conn.execute("""
                INSERT INTO zt_stocks
                (date, code, name, price, change_pct, first_zt_time,
                 lianban_days, zt_type, market_cap, days_ban)
                SELECT date, code, name, price, change_pct, first_zt_time,
                       lianban_days, zt_type, market_cap, days_ban
                FROM df
            """)
        finally:
            conn.close()

    def save_zt_reasons(self, df: pd.DataFrame):
        """保存涨停原因数据"""
        if df.empty:
            return

        conn = self._get_connection()
        try:
            # 按日期和source清空旧数据
            if "source" in df.columns:
                for (date_val, source), group in df.groupby(["date", "source"]):
                    conn.execute(
                        "DELETE FROM zt_reasons WHERE date = ? AND source = ?", [date_val, source]
                    )

            # 插入新数据
            conn.execute("""
                INSERT INTO zt_reasons
                (date, code, name, source, cate, reason)
                SELECT date, code, name, source, cate, reason
                FROM df
            """)
        finally:
            conn.close()

    def log_fetch(
        self, date_val: date, source: str, count: int, status: str = "success", message: str = ""
    ):
        """记录抓取日志"""
        conn = self._get_connection()
        try:
            conn.execute(
                """
                INSERT INTO fetch_log (date, source, count, status, message)
                VALUES (?, ?, ?, ?, ?)
            """,
                [date_val, source, count, status, message],
            )
        finally:
            conn.close()

    def query_history(self, days: int = 7) -> pd.DataFrame:
        """查询历史数据统计"""
        conn = self._get_connection()
        try:
            result = conn.execute(
                """
                SELECT date,
                       COUNT(*) as count,
                       AVG(lianban_days) as avg_lianban,
                       MAX(lianban_days) as max_lianban
                FROM zt_stocks
                WHERE date >= CURRENT_DATE - INTERVAL '%s days'
                GROUP BY date
                ORDER BY date DESC
            """
                % days
            ).fetchdf()
            return result
        finally:
            conn.close()

    def save_daily_hot_topics(
        self,
        date_val: date,
        summary_df: pd.DataFrame,
        stock_df: pd.DataFrame,
    ) -> None:
        """保存单日热点汇总和热点股票明细。"""
        conn = self._get_connection()
        try:
            conn.execute("DELETE FROM daily_hot_topic_stocks WHERE date = ?", [date_val])
            conn.execute("DELETE FROM daily_hot_topics WHERE date = ?", [date_val])

            if not summary_df.empty:
                conn.execute(
                    """
                    INSERT INTO daily_hot_topics
                    (date, topic, appearance_count, stock_count, sample_stocks, rank)
                    SELECT date, topic, appearance_count, stock_count, sample_stocks, rank
                    FROM summary_df
                    """
                )

            if not stock_df.empty:
                conn.execute(
                    """
                    INSERT INTO daily_hot_topic_stocks
                    (date, topic, code, name)
                    SELECT date, topic, code, name
                    FROM stock_df
                    """
                )
        finally:
            conn.close()

    def query_zt_stocks(self, date_val: Optional[date] = None) -> pd.DataFrame:
        """查询涨停股票数据"""
        conn = self._get_connection()
        try:
            if date_val:
                result = conn.execute(
                    "SELECT * FROM zt_stocks WHERE date = ? ORDER BY lianban_days DESC", [date_val]
                ).fetchdf()
            else:
                result = conn.execute(
                    "SELECT * FROM zt_stocks ORDER BY date DESC, lianban_days DESC"
                ).fetchdf()
            return result
        finally:
            conn.close()

    def get_latest_hot_topic_date(self) -> Optional[date]:
        """获取最新一个有热点数据的日期。"""
        conn = self._get_connection()
        try:
            result = conn.execute("SELECT MAX(date) FROM daily_hot_topics").fetchone()
            return result[0] if result else None
        finally:
            conn.close()

    def get_hot_topics_by_date(self, date_val: date) -> pd.DataFrame:
        """获取指定日期的热点汇总。"""
        conn = self._get_connection()
        try:
            return conn.execute(
                """
                SELECT date, topic, appearance_count, stock_count, sample_stocks, rank
                FROM daily_hot_topics
                WHERE date = ?
                ORDER BY rank ASC, topic ASC
                """,
                [date_val],
            ).fetchdf()
        finally:
            conn.close()

    def get_hot_topics_in_range(self, start_date: date, end_date: date) -> pd.DataFrame:
        """获取日期范围内的热点汇总。"""
        conn = self._get_connection()
        try:
            return conn.execute(
                """
                SELECT date, topic, appearance_count, stock_count, sample_stocks, rank
                FROM daily_hot_topics
                WHERE date BETWEEN ? AND ?
                ORDER BY date DESC, rank ASC, topic ASC
                """,
                [start_date, end_date],
            ).fetchdf()
        finally:
            conn.close()

    def get_hot_topic_by_date(self, date_val: date, topic: str) -> pd.DataFrame:
        """获取指定日期和热点词的汇总。"""
        conn = self._get_connection()
        try:
            return conn.execute(
                """
                SELECT date, topic, appearance_count, stock_count, sample_stocks, rank
                FROM daily_hot_topics
                WHERE date = ? AND topic = ?
                ORDER BY rank ASC
                """,
                [date_val, topic],
            ).fetchdf()
        finally:
            conn.close()

    def get_latest_hot_topic_occurrence(self, topic: str, on_or_before: date) -> pd.DataFrame:
        """获取某热点截至指定日期最近一次出现。"""
        conn = self._get_connection()
        try:
            return conn.execute(
                """
                SELECT date, topic, appearance_count, stock_count, sample_stocks, rank
                FROM daily_hot_topics
                WHERE topic = ? AND date <= ?
                ORDER BY date DESC
                LIMIT 1
                """,
                [topic, on_or_before],
            ).fetchdf()
        finally:
            conn.close()

    def get_previous_hot_topic_occurrence(self, topic: str, before_date: date) -> pd.DataFrame:
        """获取某热点在指定日期之前最近一次出现。"""
        conn = self._get_connection()
        try:
            return conn.execute(
                """
                SELECT date, topic, appearance_count, stock_count, sample_stocks, rank
                FROM daily_hot_topics
                WHERE topic = ? AND date < ?
                ORDER BY date DESC
                LIMIT 1
                """,
                [topic, before_date],
            ).fetchdf()
        finally:
            conn.close()

    def get_hot_topic_stocks(self, date_val: date, topic: str) -> pd.DataFrame:
        """获取指定日期某热点对应股票。"""
        conn = self._get_connection()
        try:
            return conn.execute(
                """
                SELECT date, topic, code, name
                FROM daily_hot_topic_stocks
                WHERE date = ? AND topic = ?
                ORDER BY code ASC, name ASC
                """,
                [date_val, topic],
            ).fetchdf()
        finally:
            conn.close()

    def query_zt_reasons(
        self, date_val: Optional[date] = None, source: Optional[str] = None
    ) -> pd.DataFrame:
        """查询涨停原因数据"""
        conn = self._get_connection()
        try:
            sql = "SELECT * FROM zt_reasons WHERE 1=1"
            params = []

            if date_val:
                sql += " AND date = ?"
                params.append(date_val)
            if source:
                sql += " AND source = ?"
                params.append(source)

            sql += " ORDER BY date DESC"
            result = conn.execute(sql, params).fetchdf()
            return result
        finally:
            conn.close()

    def get_reason_dates(self) -> list[date]:
        """获取所有有理由数据的日期。"""
        conn = self._get_connection()
        try:
            rows = conn.execute(
                """
                SELECT DISTINCT date
                FROM zt_reasons
                ORDER BY date ASC
                """
            ).fetchall()
            return [row[0] for row in rows]
        finally:
            conn.close()

    def query_fetch_logs(self, date_val: Optional[date] = None) -> pd.DataFrame:
        """查询抓取日志."""
        conn = self._get_connection()
        try:
            if date_val:
                result = conn.execute(
                    """
                    SELECT date, source, count, status, message, created_at
                    FROM fetch_log
                    WHERE date = ?
                    ORDER BY created_at DESC
                    """,
                    [date_val],
                ).fetchdf()
            else:
                result = conn.execute(
                    """
                    SELECT date, source, count, status, message, created_at
                    FROM fetch_log
                    ORDER BY created_at DESC
                    """
                ).fetchdf()
            return result
        finally:
            conn.close()

    def save_trade_dates(self, dates: list[date]):
        """批量保存交易日期到交易日历表"""
        if not dates:
            return

        conn = self._get_connection()
        try:
            for d in dates:
                conn.execute(
                    "INSERT OR IGNORE INTO trading_calendar (trade_date, is_open) VALUES (?, TRUE)",
                    [d],
                )
        finally:
            conn.close()

    def is_trade_day(self, date_val: date) -> Optional[bool]:
        """查询某天是否为交易日

        Returns:
            True: 交易日
            False: 非交易日
            None: 未知（未在数据库中）
        """
        conn = self._get_connection()
        try:
            result = conn.execute(
                "SELECT is_open FROM trading_calendar WHERE trade_date = ?", [date_val]
            ).fetchall()
            if result:
                return result[0][0]
            return None
        finally:
            conn.close()

    def query_lianban_stats(self, date_val: Optional[date] = None, days: int = 1) -> pd.DataFrame:
        """查询连板结构统计（返回最近 N 个有数据的关键交易日）"""
        conn = self._get_connection()
        try:
            if date_val and days == 1:
                sql = """
                    SELECT date,
                           COUNT(*) AS total,
                           COUNT(*) FILTER (WHERE lianban_days = 1) AS shouban,
                           COUNT(*) FILTER (WHERE lianban_days = 2) AS erban,
                           COUNT(*) FILTER (WHERE lianban_days >= 3) AS sanban_plus,
                           MAX(lianban_days) AS max_lianban,
                           ROUND(AVG(lianban_days), 2) AS avg_lianban,
                           MEDIAN(lianban_days) AS median_lianban
                    FROM zt_stocks
                    WHERE date = ?
                    GROUP BY date
                    ORDER BY date DESC
                """
                params = [date_val]
            else:
                anchor = f"'{date_val}'" if date_val else "CURRENT_DATE"
                sql = f"""
                    SELECT date,
                           COUNT(*) AS total,
                           COUNT(*) FILTER (WHERE lianban_days = 1) AS shouban,
                           COUNT(*) FILTER (WHERE lianban_days = 2) AS erban,
                           COUNT(*) FILTER (WHERE lianban_days >= 3) AS sanban_plus,
                           MAX(lianban_days) AS max_lianban,
                           ROUND(AVG(lianban_days), 2) AS avg_lianban,
                           MEDIAN(lianban_days) AS median_lianban
                    FROM zt_stocks
                    WHERE date <= {anchor}
                    GROUP BY date
                    ORDER BY date DESC
                    LIMIT {days}
                """
                params = []

            result = conn.execute(sql, params).fetchdf()
            return result
        finally:
            conn.close()

    def query_daily_count_with_ma(
        self, date_val: Optional[date] = None, days: int = 20
    ) -> pd.DataFrame:
        """查询每日涨停数及 MA5/MA10（返回最近 N 个有数据的关键交易日）"""
        conn = self._get_connection()
        try:
            anchor = f"'{date_val}'" if date_val else "CURRENT_DATE"
            result = conn.execute(
                f"""
                WITH recent AS (
                    SELECT date, COUNT(*) AS zt_count
                    FROM zt_stocks
                    WHERE date <= {anchor}
                    GROUP BY date
                    ORDER BY date DESC
                    LIMIT {days + 10}
                ),
                ordered AS (
                    SELECT date, zt_count,
                           ROUND(AVG(zt_count) OVER (ORDER BY date ROWS BETWEEN 4 PRECEDING AND CURRENT ROW), 1) AS ma5,
                           ROUND(AVG(zt_count) OVER (ORDER BY date ROWS BETWEEN 9 PRECEDING AND CURRENT ROW), 1) AS ma10
                    FROM recent
                )
                SELECT * FROM ordered ORDER BY date DESC LIMIT {days}
                """
            ).fetchdf()
            return result
        finally:
            conn.close()
