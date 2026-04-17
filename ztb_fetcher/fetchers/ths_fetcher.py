"""同花顺涨停数据抓取模块.

使用 pywencai 库获取涨停数据，并缓存 Kimi 分类结果。
"""

import json
import logging
import socket
import time
from datetime import datetime
from functools import wraps
from typing import Optional
from urllib import error, request

import pandas as pd
import pywencai

from ztb_fetcher.config import (
    THS_KIMI_CACHE_DIR,
    THS_QUERY_TEMPLATE,
    THS_SUMMARY_IMAGE_URL_TEMPLATE,
    get_config,
)
from ztb_fetcher.database import Database
from ztb_fetcher.utils.cache_manager import CacheManager
from ztb_fetcher.utils.deepseek_ocr import (
    DeepSeekOCRError,
    extract_summary_stock_categories_from_image,
)

logger = logging.getLogger(__name__)
_summary_cache = CacheManager(THS_KIMI_CACHE_DIR)
_SUMMARY_CACHE_VERSION = 2


class THSTemporaryFetchError(RuntimeError):
    """Raised when THS data source returns a transient empty response."""


def retry_on_error(max_retries: int = 2, delay_seconds: int = 10):
    """固定间隔重试装饰器

    只对特定网络/服务错误进行重试：
    - NoneType 错误（pywencai 返回 None）
    - ConnectionError, TimeoutError

    Args:
        max_retries: 最大重试次数（默认2次，共3次尝试）
        delay_seconds: 每次重试间隔秒数（默认10秒）
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    error_msg = str(e).lower()

                    # 判断是否为可重试错误
                    is_retryable = (
                        isinstance(e, THSTemporaryFetchError)
                        or "nonetype" in error_msg
                        or "connection" in error_msg
                        or "timeout" in error_msg
                        or "temporary" in error_msg
                    )

                    if not is_retryable or attempt == max_retries:
                        raise

                    logger.warning(
                        f"[THS] 第 {attempt + 1} 次尝试失败，{delay_seconds}s 后重试: {e}"
                    )
                    time.sleep(delay_seconds)

            raise last_exception

        return wrapper

    return decorator


class THSFetcher:
    """同花顺数据抓取器"""

    def __init__(self, db: Database):
        self.db = db
        self.last_fetch_metadata: dict[str, object] = {"warnings": []}

    @retry_on_error(max_retries=2, delay_seconds=10)
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
        self.last_fetch_metadata = {
            "warnings": [],
            "structured_codes": [],
            "missing_codes": [],
            "extra_codes": [],
            "cate_count": 0,
            "summary_cache_hit": False,
        }

        try:
            df = pywencai.get(query=query, sort_key="成交金额", sort_order="desc", loop=True)
            if df is None:
                raise THSTemporaryFetchError("pywencai 返回空结果，可能是接口临时异常或当日数据尚未生成")

            if df.empty:
                logger.warning(f"[THS] {date_str} 无涨停数据")
                return pd.DataFrame(), pd.DataFrame()

            logger.info(f"[THS] 获取到 {len(df)} 条原始数据")

            # 处理数据
            stocks_df, reasons_df = self._process_data(df, date_str)
            reasons_df = self._enrich_categories_from_summary_image(reasons_df, stocks_df, date_str)

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

        # 过滤掉涨停类型为空的记录（非涨停股）
        if "zt_type" in result.columns:
            before = len(result)
            result = result[result["zt_type"].notna() & (result["zt_type"] != "-")]
            after = len(result)
            if before != after:
                logger.info(f"[THS] 过滤非涨停数据: {before - after} 条被移除, 剩余 {after} 条")

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
                    "cate": None,
                    "reason": result["zt_reason"],
                }
            )

        return stocks_df, reasons_df

    def _enrich_categories_from_summary_image(
        self,
        reasons_df: pd.DataFrame,
        stocks_df: pd.DataFrame,
        date_str: str,
    ) -> pd.DataFrame:
        if reasons_df.empty or stocks_df.empty:
            return reasons_df

        cache_payload = self._load_summary_cache(date_str, expected_candidate_count=len(stocks_df))
        if cache_payload is not None:
            logger.info(f"[THS] 命中 Kimi 分类缓存: {date_str}")
            self.last_fetch_metadata["summary_cache_hit"] = True
            recognized_rows = cache_payload.get("recognized_rows") or []
        else:
            try:
                logger.info(f"[THS] 开始下载 {date_str} 分类图片")
                image_bytes, content_type = self._download_summary_image(date_str)
                logger.info(f"[THS] 开始 Kimi 图片结构化: {date_str}")
                recognized_rows = extract_summary_stock_categories_from_image(
                    image_bytes, content_type, stocks_df, date_str
                )
            except (DeepSeekOCRError, RuntimeError, TimeoutError, socket.timeout) as exc:
                self._append_warning(f"THS 图片结构化失败: {exc}")
                return reasons_df

            self._save_summary_cache(date_str, len(stocks_df), recognized_rows)

        recognized_df = pd.DataFrame(recognized_rows)
        if recognized_df.empty:
            self._append_warning("THS 图片分类识别结果为空")
            return reasons_df

        recognized_codes = {
            code for code in recognized_df["code"].astype(str) if len(code) == 6 and code.isdigit()
        }
        ths_codes = set(stocks_df["code"].astype(str))
        missing_codes = sorted(ths_codes - recognized_codes)
        extra_codes = sorted(recognized_codes - ths_codes)

        self.last_fetch_metadata["structured_codes"] = sorted(recognized_codes)
        self.last_fetch_metadata["missing_codes"] = missing_codes
        self.last_fetch_metadata["extra_codes"] = extra_codes

        if len(recognized_codes) != len(ths_codes):
            self._append_warning(
                f"THS 图片分类股票数与问财不一致: 图片 {len(recognized_codes)} / 问财 {len(ths_codes)}"
            )
        if missing_codes:
            self._append_warning(f"THS 图片分类缺少代码: {', '.join(missing_codes)}")
        if extra_codes:
            self._append_warning(f"THS 图片分类多出代码: {', '.join(extra_codes)}")

        cate_map = self._build_cate_map(recognized_df, reasons_df)
        if not cate_map:
            return reasons_df

        enriched_df = reasons_df.copy()
        enriched_df["cate"] = enriched_df["code"].astype(str).map(cate_map)
        self.last_fetch_metadata["cate_count"] = int(enriched_df["cate"].fillna("").ne("").sum())
        return enriched_df

    def _build_cate_map(self, recognized_df: pd.DataFrame, reasons_df: pd.DataFrame) -> dict[str, str]:
        code_to_codes = (
            reasons_df.groupby(reasons_df["code"].astype(str))["code"].agg(lambda values: list(values.unique()))
        ).to_dict()
        name_to_codes = (
            reasons_df.groupby(reasons_df["name"].astype(str))["code"].agg(lambda values: list(values.unique()))
        ).to_dict()

        cate_map: dict[str, str] = {}
        for _, row in recognized_df.iterrows():
            code = str(row.get("code") or "").strip()
            name = str(row.get("name") or "").strip()
            cate = str(row.get("cate") or "").strip()
            if not cate:
                continue

            matched_codes: list[str] = []
            if code and code in code_to_codes:
                matched_codes = code_to_codes[code]
            elif name and name in name_to_codes:
                matched_codes = name_to_codes[name]

            if len(matched_codes) != 1:
                if name:
                    self._append_warning(f"THS 图片分类名称冲突: {name}")
                continue

            matched_code = matched_codes[0]
            existing_cate = cate_map.get(matched_code)
            if existing_cate and existing_cate != cate:
                self._append_warning(f"THS 图片分类名称冲突: {matched_code}")
                continue
            cate_map[matched_code] = cate

        return cate_map

    def _download_summary_image(self, date_str: str) -> tuple[bytes, str]:
        url_template = get_config("ths_summary_image_url_template", THS_SUMMARY_IMAGE_URL_TEMPLATE)
        url = str(url_template).format(date_str=date_str)
        req = request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with request.urlopen(req, timeout=60) as resp:
                return resp.read(), resp.headers.get_content_type() or "image/png"
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {exc.code}: {body}") from exc
        except error.URLError as exc:
            raise RuntimeError(str(exc.reason)) from exc

    def _append_warning(self, message: str) -> None:
        warnings = self.last_fetch_metadata.setdefault("warnings", [])
        if isinstance(warnings, list):
            warnings.append(message)

    def _load_summary_cache(
        self, date_str: str, *, expected_candidate_count: int
    ) -> dict[str, object] | None:
        cached_text = _summary_cache.get(date_str, suffix=".json")
        if cached_text is None:
            return None

        try:
            payload = json.loads(cached_text)
        except json.JSONDecodeError:
            logger.warning(f"[THS] Kimi 分类缓存损坏，忽略: {date_str}")
            return None

        if not isinstance(payload, dict):
            return None

        if payload.get("version") != _SUMMARY_CACHE_VERSION:
            logger.info(f"[THS] Kimi 分类缓存版本不匹配，忽略: {date_str}")
            return None

        candidate_count = payload.get("candidate_count")
        if candidate_count != expected_candidate_count:
            logger.info(
                f"[THS] Kimi 分类缓存候选数量不匹配，忽略: {date_str} cache={candidate_count} current={expected_candidate_count}"
            )
            return None

        recognized_rows = payload.get("recognized_rows")
        if not isinstance(recognized_rows, list):
            return None

        return {
            "recognized_rows": recognized_rows,
        }

    def _save_summary_cache(
        self,
        date_str: str,
        candidate_count: int,
        recognized_rows: list[dict[str, str]],
    ) -> None:
        payload = {
            "version": _SUMMARY_CACHE_VERSION,
            "date": date_str,
            "candidate_count": candidate_count,
            "recognized_rows": recognized_rows,
        }
        _summary_cache.set(date_str, json.dumps(payload, ensure_ascii=False), suffix=".json")

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
