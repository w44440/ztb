"""同花顺涨停数据抓取模块

使用 pywencai 库获取涨停数据
"""

import logging
from datetime import date, datetime
from typing import Optional

import pandas as pd
import pywencai

from ztb_fetcher.config import THS_QUERY_TEMPLATE
from ztb_fetcher.database import Database

logger = logging.getLogger(__name__)


class THSFetcher:
    """同花顺数据抓取器"""

    def __init__(self, db: Database):
        self.db = db

    def fetch(self, date_str: Optional[str] = None) -> tuple[pd.DataFrame, pd.DataFrame]:
        """获取涨停数据

        Args:
            date_str: 日期字符串，格式 YYYYMMDD，None 表示今天

        Returns:
            tuple: (zt_stocks_df, zt_reasons_df)
        """
        if date_str is None:
            date_str = datetime.now().strftime("%Y%m%d")

        logger.info(f"[THS] 开始获取 {date_str} 的涨停数据")

        query = THS_QUERY_TEMPLATE.format(date_str=date_str)
        logger.info(f"[THS] 查询语句: {query}")

        try:
            df = pywencai.get(query=query, sort_key="成交金额", sort_order="desc")

            if df.empty:
                logger.warning(f"[THS] {date_str} 无涨停数据")
                return pd.DataFrame(), pd.DataFrame()

            logger.info(f"[THS] 获取到 {len(df)} 条原始数据")

            # 处理数据
            stocks_df, reasons_df = self._process_data(df, date_str)

            # 保存到数据库
            self.db.save_zt_stocks(stocks_df)
            self.db.save_zt_reasons(reasons_df)
            self.db.log_fetch(
                date_val=pd.to_datetime(date_str, format="%Y%m%d").date(),
                source="ths",
                count=len(stocks_df),
                status="success",
            )

            logger.info(
                f"[THS] ✅ {date_str} 数据保存成功: {len(stocks_df)} 条股票, {len(reasons_df)} 条原因"
            )
            return stocks_df, reasons_df

        except Exception as e:
            logger.error(f"[THS] ❌ 获取数据失败: {e}")
            self.db.log_fetch(
                date_val=pd.to_datetime(date_str, format="%Y%m%d").date(),
                source="ths",
                count=0,
                status="failed",
                message=str(e),
            )
            raise

    def _process_data(self, df: pd.DataFrame, date_str: str) -> tuple[pd.DataFrame, pd.DataFrame]:
        """处理原始数据，分离为股票基础数据和原因数据

        Returns:
            tuple: (stocks_df, reasons_df)
        """
        date_obj = pd.to_datetime(date_str, format="%Y%m%d").date()

        # 字段映射
        key_mapping = {
            "股票代码": "code",
            "股票简称": "name",
            "最新价": "price",
            "最新涨跌幅": "change_pct",
            f"首次涨停时间[{date_str}]": "first_zt_time",
            f"连续涨停天数[{date_str}]": "lianban_days",
            f"涨停原因类别[{date_str}]": "zt_reason",
            f"涨停类型[{date_str}]": "zt_type",
            f"a股市值(不含限售股)[{date_str}]": "market_cap",
            f"几天几板[{date_str}]": "days_ban",
        }

        # 选择存在的列
        available_cols = [c for c in key_mapping.keys() if c in df.columns]
        result = df[available_cols].copy()
        result.columns = [key_mapping[c] for c in available_cols]

        # 添加日期字段
        result["date"] = date_obj

        # 去掉 code 后缀 (603538.SH -> 603538)
        if "code" in result.columns:
            result["code"] = result["code"].str.split(".").str[0]

        # 分离股票基础数据和原因数据
        stock_cols = [
            "date",
            "code",
            "name",
            "price",
            "change_pct",
            "first_zt_time",
            "lianban_days",
            "zt_type",
            "market_cap",
            "days_ban",
        ]
        stocks_df = result[[c for c in stock_cols if c in result.columns]].copy()

        # 构建原因数据（如果存在 zt_reason）
        reasons_df = pd.DataFrame()
        if "zt_reason" in result.columns:
            reasons_df = pd.DataFrame(
                {
                    "date": result["date"],
                    "code": result["code"],
                    "name": result["name"],
                    "source": "ths",
                    "cate": result["zt_reason"],
                    "reason": result["zt_reason"],
                }
            )

        return stocks_df, reasons_df

    def fetch_range(
        self, start_date: str, end_date: str
    ) -> list[tuple[pd.DataFrame, pd.DataFrame]]:
        """批量获取日期范围的涨停数据

        Args:
            start_date: 开始日期 YYYYMMDD
            end_date: 结束日期 YYYYMMDD

        Returns:
            list: 每日数据的列表
        """
        results = []
        date_range = pd.date_range(start=start_date, end=end_date, freq="D")

        for d in date_range:
            date_str = d.strftime("%Y%m%d")
            try:
                result = self.fetch(date_str)
                results.append(result)
            except Exception as e:
                logger.error(f"[THS] {date_str} 抓取失败: {e}")
                continue

        return results
