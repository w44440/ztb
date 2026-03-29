"""交易日日历模块"""

import logging
from datetime import date, datetime
from typing import Optional

import akshare as ak
import pandas as pd

from ztb_fetcher.database import Database

logger = logging.getLogger(__name__)


class TradingCalendar:
    """交易日日历管理"""

    def __init__(self, db: Database):
        self.db = db
        self._month_cache = set()  # 记录已加载的月份

    def is_trade_day(self, date_str: str) -> bool:
        """检查是否为交易日

        Args:
            date_str: 日期字符串，格式 YYYYMMDD

        Returns:
            True 为交易日，False 为非交易日
        """
        date_val = datetime.strptime(date_str, "%Y%m%d").date()
        year = date_str[:4]
        month = date_str[4:6]
        month_key = f"{year}-{month}"

        # 先查数据库
        result = self.db.is_trade_day(date_val)
        if result is not None:
            return result

        # 数据库未命中，拉取当月交易日
        self._fetch_and_cache_month(year, month)

        # 再查数据库
        result = self.db.is_trade_day(date_val)
        return result if result is not None else False

    def _fetch_and_cache_month(self, year: str, month: str):
        """获取某月的交易日并缓存到数据库

        Args:
            year: 年份，格式 YYYY
            month: 月份，格式 MM
        """
        month_key = f"{year}-{month}"

        # 避免重复加载同一月份
        if month_key in self._month_cache:
            return

        try:
            logger.info(f"[TradingCalendar] 从 akshare 拉取 {month_key} 交易日")

            # 从 akshare 获取全年交易日列表
            df = ak.tool_trade_date_hist_sina()
            df["trade_date"] = pd.to_datetime(df["trade_date"])

            # 筛选目标月份
            month_start = f"{year}-{month}-01"
            month_end_date = pd.to_datetime(month_start) + pd.DateOffset(months=1)

            month_df = df[
                (df["trade_date"] >= month_start)
                & (df["trade_date"] < month_end_date)
            ]

            if month_df.empty:
                logger.warning(f"[TradingCalendar] {month_key} 无交易日数据")
                return

            # 将日期转换为 date 对象并保存到数据库
            trade_dates = [d.date() for d in month_df["trade_date"]]
            self.db.save_trade_dates(trade_dates)

            logger.info(f"[TradingCalendar] ✅ {month_key} 保存 {len(trade_dates)} 个交易日")

            # 标记已加载
            self._month_cache.add(month_key)

        except Exception as e:
            logger.error(f"[TradingCalendar] ❌ 拉取 {month_key} 失败: {e}")
            raise
