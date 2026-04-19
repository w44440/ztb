import json
import unittest
from unittest.mock import Mock, patch

import pandas as pd

from ztb_fetcher.fetchers.ths_fetcher import THSFetcher
from ztb_fetcher.ocr.local import LocalOCRError


def _sample_wencai_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "股票代码": "600000.SH",
                "股票简称": "浦发银行",
                "最新价": 10.0,
                "最新涨跌幅": 10.0,
                "首次涨停时间[20260415]": "09:30:00",
                "连续涨停天数[20260415]": 1,
                "涨停原因类别[20260415]": "银行+国企改革",
                "涨停类型[20260415]": "一字板",
                "a股市值(不含限售股)[20260415]": 1000000000,
                "几天几板[20260415]": "1天1板",
            },
            {
                "股票代码": "000001.SZ",
                "股票简称": "平安银行",
                "最新价": 12.0,
                "最新涨跌幅": 10.0,
                "首次涨停时间[20260415]": "09:31:00",
                "连续涨停天数[20260415]": 2,
                "涨停原因类别[20260415]": "金融科技+AI",
                "涨停类型[20260415]": "换手板",
                "a股市值(不含限售股)[20260415]": 2000000000,
                "几天几板[20260415]": "2天2板",
            },
        ]
    )


class THSFetcherTest(unittest.TestCase):
    def setUp(self):
        self.load_cache_patcher = patch(
            "ztb_fetcher.fetchers.ths_fetcher.THSFetcher._load_summary_cache",
            return_value=None,
        )
        self.save_cache_patcher = patch(
            "ztb_fetcher.fetchers.ths_fetcher.THSFetcher._save_summary_cache"
        )
        self.load_cache_patcher.start()
        self.save_cache_patcher.start()

    def tearDown(self):
        self.save_cache_patcher.stop()
        self.load_cache_patcher.stop()

    def test_fetch_enriches_categories_with_code_and_name_fallback(self):
        db = Mock()
        fetcher = THSFetcher(db)

        with (
            patch(
                "ztb_fetcher.fetchers.ths_fetcher.pywencai.get", return_value=_sample_wencai_df()
            ),
            patch.object(fetcher, "_download_summary_image", return_value=(b"img", "image/png")),
            patch(
                "ztb_fetcher.fetchers.ths_fetcher.extract_summary_stock_categories_from_image",
                return_value=[
                    {"code": "600000", "name": "浦发银行", "cate": "金融"},
                    {"code": "", "name": "平安银行", "cate": "银行"},
                    {"code": "999999", "name": "不存在", "cate": "其他"},
                ],
            ),
        ):
            stocks_df, reasons_df = fetcher.fetch("20260415")

        self.assertEqual(len(stocks_df), 2)
        cate_map = dict(zip(reasons_df["code"], reasons_df["cate"].fillna("")))
        self.assertEqual(cate_map["600000"], "金融")
        self.assertEqual(cate_map["000001"], "银行")
        self.assertEqual(fetcher.last_fetch_metadata["structured_codes"], ["600000", "999999"])
        self.assertIn("THS 图片分类缺少代码: 000001", fetcher.last_fetch_metadata["warnings"])
        self.assertIn("THS 图片分类多出代码: 999999", fetcher.last_fetch_metadata["warnings"])
        self.assertEqual(fetcher.last_fetch_metadata["cate_count"], 2)
        db.save_zt_stocks.assert_called_once()
        db.save_zt_reasons.assert_called_once()

    def test_fetch_uses_cached_ocr_result_without_model_calls(self):
        self.load_cache_patcher.stop()
        self.save_cache_patcher.stop()
        db = Mock()
        fetcher = THSFetcher(db)
        cached_payload = {
            "version": 4,
            "candidate_count": 2,
            "recognized_rows": [
                {"code": "600000", "name": "浦发银行", "cate": "金融"},
                {"code": "", "name": "平安银行", "cate": "银行"},
            ],
        }

        with (
            patch(
                "ztb_fetcher.fetchers.ths_fetcher.pywencai.get", return_value=_sample_wencai_df()
            ),
            patch(
                "ztb_fetcher.fetchers.ths_fetcher._summary_cache.get",
                return_value=json.dumps(cached_payload, ensure_ascii=False),
            ),
            patch.object(fetcher, "_download_summary_image") as download_image,
            patch(
                "ztb_fetcher.fetchers.ths_fetcher.extract_summary_stock_categories_from_image"
            ) as extract,
        ):
            _stocks_df, reasons_df = fetcher.fetch("20260415")

        cate_map = dict(zip(reasons_df["code"], reasons_df["cate"].fillna("")))
        self.assertEqual(cate_map["600000"], "金融")
        self.assertEqual(cate_map["000001"], "银行")
        self.assertTrue(fetcher.last_fetch_metadata["summary_cache_hit"])
        download_image.assert_not_called()
        extract.assert_not_called()

    def test_fetch_saves_ocr_result_to_cache_after_success(self):
        self.load_cache_patcher.stop()
        self.save_cache_patcher.stop()
        db = Mock()
        fetcher = THSFetcher(db)

        with (
            patch(
                "ztb_fetcher.fetchers.ths_fetcher.pywencai.get", return_value=_sample_wencai_df()
            ),
            patch(
                "ztb_fetcher.fetchers.ths_fetcher.THSFetcher._load_summary_cache",
                return_value=None,
            ),
            patch("ztb_fetcher.fetchers.ths_fetcher.THSFetcher._save_summary_cache") as save_cache,
            patch.object(fetcher, "_download_summary_image", return_value=(b"img", "image/png")),
            patch(
                "ztb_fetcher.fetchers.ths_fetcher.extract_summary_stock_categories_from_image",
                return_value=[{"code": "600000", "name": "浦发银行", "cate": "金融"}],
            ),
        ):
            fetcher.fetch("20260415")

        save_cache.assert_called_once_with(
            "20260415",
            2,
            [{"code": "600000", "name": "浦发银行", "cate": "金融"}],
        )

    def test_fetch_ignores_legacy_cache_without_version(self):
        self.load_cache_patcher.stop()
        self.save_cache_patcher.stop()
        db = Mock()
        fetcher = THSFetcher(db)
        legacy_payload = {
            "ocr_text": "ocr text",
            "recognized_rows": [{"code": "600000", "name": "浦发银行", "cate": "金融"}],
        }

        with (
            patch(
                "ztb_fetcher.fetchers.ths_fetcher.pywencai.get", return_value=_sample_wencai_df()
            ),
            patch(
                "ztb_fetcher.fetchers.ths_fetcher._summary_cache.get",
                return_value=json.dumps(legacy_payload, ensure_ascii=False),
            ),
            patch.object(fetcher, "_download_summary_image", return_value=(b"img", "image/png")),
            patch(
                "ztb_fetcher.fetchers.ths_fetcher.extract_summary_stock_categories_from_image",
                return_value=[{"code": "600000", "name": "浦发银行", "cate": "金融"}],
            ) as extract,
        ):
            fetcher.fetch("20260415")

        extract.assert_called_once()

    def test_fetch_skips_conflicting_category_assignments(self):
        db = Mock()
        fetcher = THSFetcher(db)

        with (
            patch(
                "ztb_fetcher.fetchers.ths_fetcher.pywencai.get", return_value=_sample_wencai_df()
            ),
            patch.object(fetcher, "_download_summary_image", return_value=(b"img", "image/png")),
            patch(
                "ztb_fetcher.fetchers.ths_fetcher.extract_summary_stock_categories_from_image",
                return_value=[
                    {"code": "600000", "name": "浦发银行", "cate": "金融"},
                    {"code": "", "name": "浦发银行", "cate": "银行"},
                ],
            ),
        ):
            _stocks_df, reasons_df = fetcher.fetch("20260415")

        cate_map = dict(zip(reasons_df["code"], reasons_df["cate"].fillna("")))
        self.assertEqual(cate_map["600000"], "金融")
        self.assertEqual(cate_map["000001"], "")
        self.assertIn("THS 图片分类名称冲突: 600000", fetcher.last_fetch_metadata["warnings"])
        self.assertEqual(fetcher.last_fetch_metadata["cate_count"], 1)

    def test_fetch_keeps_ths_success_when_image_structuring_fails(self):
        db = Mock()
        fetcher = THSFetcher(db)

        with (
            patch(
                "ztb_fetcher.fetchers.ths_fetcher.pywencai.get", return_value=_sample_wencai_df()
            ),
            patch.object(fetcher, "_download_summary_image", return_value=(b"img", "image/png")),
            patch(
                "ztb_fetcher.fetchers.ths_fetcher.extract_summary_stock_categories_from_image",
                side_effect=LocalOCRError("paddle down"),
            ),
        ):
            _stocks_df, reasons_df = fetcher.fetch("20260415")

        self.assertTrue(reasons_df["cate"].isna().all())
        self.assertEqual(fetcher.last_fetch_metadata["cate_count"], 0)
        self.assertIn("THS 图片 OCR 解析失败: paddle down", fetcher.last_fetch_metadata["warnings"])

    def test_fetch_keeps_ths_success_when_image_structuring_times_out(self):
        db = Mock()
        fetcher = THSFetcher(db)

        with (
            patch(
                "ztb_fetcher.fetchers.ths_fetcher.pywencai.get", return_value=_sample_wencai_df()
            ),
            patch.object(fetcher, "_download_summary_image", return_value=(b"img", "image/png")),
            patch(
                "ztb_fetcher.fetchers.ths_fetcher.extract_summary_stock_categories_from_image",
                side_effect=TimeoutError("timed out"),
            ),
        ):
            stocks_df, reasons_df = fetcher.fetch("20260415")

        self.assertEqual(len(stocks_df), 2)
        self.assertTrue(reasons_df["cate"].isna().all())
        self.assertIn("THS 图片 OCR 解析失败: timed out", fetcher.last_fetch_metadata["warnings"])
        db.save_zt_stocks.assert_called_once()
        db.save_zt_reasons.assert_called_once()


if __name__ == "__main__":
    unittest.main()
