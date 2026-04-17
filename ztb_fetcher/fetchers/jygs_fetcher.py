"""韭研公社涨停数据抓取模块

通过网页抓取获取韭研公社涨停板数据，支持缓存机制
"""

import logging
from datetime import datetime
from functools import partial
from typing import Optional

import pandas as pd
from playwright.sync_api import Page

from ztb_fetcher.config import JYGS_BASE_URL, JYGS_CACHE_DIR
from ztb_fetcher.database import Database
from ztb_fetcher.utils.cache_manager import CacheManager
from ztb_fetcher.utils.error_handler import (
    PlaywrightAuthError,
    PlaywrightBrowserError,
    PlaywrightNavigationError,
)
from ztb_fetcher.utils.playwright_util import get_data_persistent

logger = logging.getLogger(__name__)

# 创建缓存管理器实例
_cache = CacheManager(JYGS_CACHE_DIR, use_monthly_subfolder=True)


class JYGSFetcher:
    """韭研公社数据抓取器"""

    _NON_AUTH_COOKIE_NAMES = {"HMACCOUNT", "time"}
    _NON_AUTH_COOKIE_PREFIXES = ("Hm_",)

    def __init__(self, db: Database):
        self.db = db

    def fetch(
        self, date_str: Optional[str] = None, filter_codes: Optional[set] = None
    ) -> pd.DataFrame:
        """获取韭研公社涨停数据

        Args:
            date_str: 日期字符串，格式 YYYYMMDD，None 表示今天
            filter_codes: 过滤股票代码集合，只保留这些股票

        Returns:
            DataFrame: zt_reasons 格式的数据
        """
        if date_str is None:
            date_str = datetime.now().strftime("%Y%m%d")

        formatted_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
        logger.info(f"[JYGS] 开始获取 {formatted_date} 的涨停数据")

        # 检查缓存（缓存不过滤，解析时再过滤）
        cached_text = _cache.get(formatted_date, suffix=".txt")
        if cached_text is not None:
            logger.info(f"[JYGS] 从缓存读取 {formatted_date} 数据")
            df = self._parse_data(cached_text.split("\n"), formatted_date, filter_codes)
            if not df.empty:
                self._save_to_db(df, formatted_date)
                return df

        # 使用 Playwright 持久化上下文抓取
        try:
            fetch_data = partial(self._fetch_single_day, formatted_date)
            texts = get_data_persistent(JYGS_BASE_URL, fetch_data, self._check_login)

            if texts and texts[0]:
                df = self._parse_data(texts[0].split("\n"), formatted_date, filter_codes)
                if not df.empty:
                    self._save_to_db(df, formatted_date)
                    # 保存缓存（原始数据不过滤）
                    _cache.set(formatted_date, texts[0], suffix=".txt")
                    logger.info(f"[JYGS] ✅ {formatted_date} 数据保存成功: {len(df)} 条")
                    return df

            logger.warning(f"[JYGS] ⚠️ {formatted_date} 没有抓取到数据")
            return pd.DataFrame()

        except (PlaywrightBrowserError, PlaywrightNavigationError, PlaywrightAuthError) as e:
            logger.error(f"[JYGS] ❌ Playwright 错误: {e}")
            self.db.log_fetch(
                date_val=datetime.strptime(date_str, "%Y%m%d").date(),
                source="jygs",
                count=0,
                status="failed",
                message=str(e),
            )
            raise

    def fetch_range(self, start_date: str, end_date: str) -> pd.DataFrame:
        """批量获取日期范围的涨停数据

        Args:
            start_date: 开始日期 YYYYMMDD
            end_date: 结束日期 YYYYMMDD

        Returns:
            DataFrame: 合并后的数据
        """
        date_range = pd.date_range(start=start_date, end=end_date, freq="D")
        all_data = []

        for d in date_range:
            date_str = d.strftime("%Y%m%d")
            try:
                df = self.fetch(date_str)
                if not df.empty:
                    all_data.append(df)
            except Exception as e:
                logger.error(f"[JYGS] {date_str} 抓取失败: {e}")
                continue

        if all_data:
            return pd.concat(all_data, ignore_index=True)
        return pd.DataFrame()

    def _fetch_single_day(self, formatted_date: str, page: Page) -> list:
        """抓取单个日期的数据（在 Playwright 上下文中执行）"""
        logger.info(f"[JYGS] 开始抓取 {formatted_date} 的数据")

        # 访问页面
        page.goto(f"{JYGS_BASE_URL}{formatted_date}")
        page.wait_for_load_state("networkidle", timeout=10000)

        # 检查登录
        if not self._check_login(page):
            raise PlaywrightAuthError(f"页面需要登录: {formatted_date}")

        # 尝试点击"全部异动解析"
        try:
            page.get_by_text("全部异动解析").click(timeout=5000)
            page.wait_for_timeout(2000)
        except Exception:
            logger.debug(f"[JYGS] {formatted_date} 点击'全部异动解析'失败，继续尝试抓取")

        # 抓取数据
        text = self._extract_data(page, formatted_date)

        if text:
            return [text]
        return []

    def _extract_data(self, page: Page, date_str: str) -> str:
        """从页面提取数据"""
        rows = []
        stock_groups = page.locator("li.module")

        if stock_groups.count() == 0:
            logger.warning(f"[JYGS] {date_str} 没有找到股票分组数据")
            return ""

        for i_outer in range(1, stock_groups.count()):
            try:
                stock_group = stock_groups.nth(i_outer)
                group_name_elements = stock_group.locator("div.count-filed").all_text_contents()

                if not group_name_elements:
                    continue

                group_name = group_name_elements[0]
                if not group_name:
                    continue

                group_name, _ = group_name.split()

                # 跳过ST板块
                if "ST" in group_name.upper():
                    logger.debug(f"[JYGS] {date_str} 跳过ST板块: {group_name}")
                    continue

                stocks = stock_group.locator("li.row")

                for i_inner in range(stocks.count()):
                    try:
                        stock = stocks.nth(i_inner)
                        stock_properties = stock.locator("div.td")

                        if stock_properties.count() < 5:
                            continue

                        # 获取股票名称和代码
                        stock_name_element = stock_properties.nth(0).all_text_contents()
                        if not stock_name_element:
                            continue

                        stock_name_full = stock_name_element[0]
                        if not stock_name_full or "," in stock_name_full:
                            continue

                        stock_name, stock_code = stock_name_full.split()
                        # 去掉股票代码前缀字母
                        stock_code = stock_code[2:] if len(stock_code) > 6 else stock_code

                        # 获取股票描述
                        stock_desc_elements = (
                            stock_properties.nth(4).locator("pre").all_text_contents()
                        )
                        if not stock_desc_elements:
                            continue

                        stock_desc = stock_desc_elements[0]
                        if not stock_desc:
                            continue

                        topics, _ = stock_desc.split("\n", 1)

                        # 过滤ST股票
                        if "ST" in stock_name.upper():
                            continue

                        row = f"{date_str},{stock_code},{stock_name},{group_name},{topics}"
                        rows.append(row)

                    except Exception as e:
                        logger.debug(f"[JYGS] {date_str} 股票 {i_inner} 抓取失败: {e}")
                        continue

            except Exception as e:
                logger.debug(f"[JYGS] {date_str} 分组 {i_outer} 抓取失败: {e}")
                continue

        logger.info(f"[JYGS] ✅ {date_str} 数据抓取完成,共 {len(rows)} 条记录")
        return "\n".join(rows)

    def _parse_data(
        self, lines: list[str], date_str: str, filter_codes: Optional[set] = None
    ) -> pd.DataFrame:
        """解析文本数据为 DataFrame"""
        parsed_data = []

        for line in lines:
            if not line.strip():
                continue

            try:
                parts = line.strip().split(",")
                if len(parts) == 5:
                    code = parts[1]
                    # 如果有过滤列表，只保留列表中的股票
                    if filter_codes and code not in filter_codes:
                        continue
                    parsed_data.append(
                        {
                            "date": pd.to_datetime(parts[0]).date(),
                            "code": code,
                            "name": parts[2],
                            "source": "jygs",
                            "cate": parts[3],
                            "reason": parts[4],
                        }
                    )
            except Exception as e:
                logger.debug(f"[JYGS] 解析行失败: {e}, 行内容: {line}")
                continue

        return pd.DataFrame(parsed_data)

    def _save_to_db(self, df: pd.DataFrame, date_str: str):
        """保存数据到数据库"""
        if df.empty:
            return

        self.db.save_zt_reasons(df)
        self.db.log_fetch(
            date_val=datetime.strptime(date_str, "%Y-%m-%d").date(),
            source="jygs",
            count=len(df),
            status="success",
        )

    @staticmethod
    def _check_login(page: Page) -> bool:
        """检查是否已登录韭研公社"""
        try:
            page.wait_for_load_state("networkidle")
            login_markers = [
                page.get_by_text("登录").first,
                page.get_by_text("注册").first,
                page.locator('button:has-text("登录")').first,
                page.locator('a:has-text("登录")').first,
                page.locator('a:has-text("注册")').first,
            ]
            for locator in login_markers:
                try:
                    if locator.is_visible(timeout=1000):
                        return False
                except Exception:
                    continue

            cookies = page.context.cookies(["https://www.jiuyangongshe.com/"])
            for cookie in cookies:
                name = str(cookie.get("name") or "")
                if not name:
                    continue
                if name in JYGSFetcher._NON_AUTH_COOKIE_NAMES:
                    continue
                if any(name.startswith(prefix) for prefix in JYGSFetcher._NON_AUTH_COOKIE_PREFIXES):
                    continue
                return True
            return False
        except Exception:
            return False
