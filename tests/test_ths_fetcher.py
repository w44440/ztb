import json
import os
import socket
import unittest
from unittest.mock import Mock, patch
from urllib import error

import pandas as pd

from ztb_fetcher.fetchers.ths_fetcher import THSFetcher
from ztb_fetcher.utils.deepseek_ocr import (
    DeepSeekOCRError,
    extract_summary_stock_categories_from_image,
)


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


class _FakeHTTPResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def read(self):
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


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
            patch("ztb_fetcher.fetchers.ths_fetcher.pywencai.get", return_value=_sample_wencai_df()),
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

    def test_fetch_uses_cached_kimi_result_without_model_calls(self):
        self.load_cache_patcher.stop()
        self.save_cache_patcher.stop()
        db = Mock()
        fetcher = THSFetcher(db)
        cached_payload = {
            "version": 2,
            "candidate_count": 2,
            "recognized_rows": [
                {"code": "600000", "name": "浦发银行", "cate": "金融"},
                {"code": "", "name": "平安银行", "cate": "银行"},
            ],
        }

        with (
            patch("ztb_fetcher.fetchers.ths_fetcher.pywencai.get", return_value=_sample_wencai_df()),
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

    def test_fetch_saves_kimi_result_to_cache_after_success(self):
        self.load_cache_patcher.stop()
        self.save_cache_patcher.stop()
        db = Mock()
        fetcher = THSFetcher(db)

        with (
            patch("ztb_fetcher.fetchers.ths_fetcher.pywencai.get", return_value=_sample_wencai_df()),
            patch(
                "ztb_fetcher.fetchers.ths_fetcher.THSFetcher._load_summary_cache",
                return_value=None,
            ),
            patch(
                "ztb_fetcher.fetchers.ths_fetcher.THSFetcher._save_summary_cache"
            ) as save_cache,
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
            patch("ztb_fetcher.fetchers.ths_fetcher.pywencai.get", return_value=_sample_wencai_df()),
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
            patch("ztb_fetcher.fetchers.ths_fetcher.pywencai.get", return_value=_sample_wencai_df()),
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
            patch("ztb_fetcher.fetchers.ths_fetcher.pywencai.get", return_value=_sample_wencai_df()),
            patch.object(fetcher, "_download_summary_image", return_value=(b"img", "image/png")),
            patch(
                "ztb_fetcher.fetchers.ths_fetcher.extract_summary_stock_categories_from_image",
                side_effect=DeepSeekOCRError("kimi down"),
            ),
        ):
            _stocks_df, reasons_df = fetcher.fetch("20260415")

        self.assertTrue(reasons_df["cate"].isna().all())
        self.assertEqual(fetcher.last_fetch_metadata["cate_count"], 0)
        self.assertIn("THS 图片结构化失败: kimi down", fetcher.last_fetch_metadata["warnings"])

    def test_fetch_keeps_ths_success_when_image_structuring_times_out(self):
        db = Mock()
        fetcher = THSFetcher(db)

        with (
            patch("ztb_fetcher.fetchers.ths_fetcher.pywencai.get", return_value=_sample_wencai_df()),
            patch.object(fetcher, "_download_summary_image", return_value=(b"img", "image/png")),
            patch(
                "ztb_fetcher.fetchers.ths_fetcher.extract_summary_stock_categories_from_image",
                side_effect=TimeoutError("timed out"),
            ),
        ):
            stocks_df, reasons_df = fetcher.fetch("20260415")

        self.assertEqual(len(stocks_df), 2)
        self.assertTrue(reasons_df["cate"].isna().all())
        self.assertIn("THS 图片结构化失败: timed out", fetcher.last_fetch_metadata["warnings"])
        db.save_zt_stocks.assert_called_once()
        db.save_zt_reasons.assert_called_once()


class DeepSeekOCRTest(unittest.TestCase):
    def test_extract_summary_stock_categories_from_image_uses_kimi_chat_completions(self):
        captured = {}
        stocks_df = pd.DataFrame(
            [{"code": "600000", "name": "浦发银行"}, {"code": "000001", "name": "平安银行"}]
        )

        def _fake_urlopen(req, timeout):
            captured["url"] = req.full_url
            captured["payload"] = json.loads(req.data.decode("utf-8"))
            captured["timeout"] = timeout
            return _FakeHTTPResponse(
                {
                    "choices": [
                        {
                            "message": {
                                "content": '```json\n[{"code":"600000","name":"浦发银行","cate":"金融"}]\n```'
                            }
                        }
                    ]
                }
            )

        with (
            patch("ztb_fetcher.utils.deepseek_ocr.get_config") as get_config,
            patch("ztb_fetcher.utils.deepseek_ocr.request.urlopen", side_effect=_fake_urlopen),
            patch.dict(os.environ, {"MOONSHOT_API_KEY": "test-key"}, clear=True),
        ):
            get_config.side_effect = lambda key, default=None: {
                "kimi_model": "kimi-k2.5",
                "kimi_base_url": "https://api.moonshot.cn/v1",
            }.get(key, default)
            result = extract_summary_stock_categories_from_image(
                b"fake", "image/png", stocks_df, "20260415"
            )

        self.assertEqual(result, [{"code": "600000", "name": "浦发银行", "cate": "金融"}])
        self.assertEqual(captured["url"], "https://api.moonshot.cn/v1/chat/completions")
        self.assertEqual(captured["payload"]["model"], "kimi-k2.5")
        self.assertEqual(captured["payload"]["thinking"], {"type": "disabled"})
        self.assertEqual(captured["payload"]["messages"][1]["content"][0]["type"], "image_url")
        self.assertTrue(
            captured["payload"]["messages"][1]["content"][0]["image_url"]["url"].startswith(
                "data:image/png;base64,"
            )
        )
        self.assertIn("候选股票列表", captured["payload"]["messages"][1]["content"][1]["text"])
        self.assertEqual(captured["timeout"], 180)

    def test_extract_summary_stock_categories_from_image_raises_for_invalid_json(self):
        stocks_df = pd.DataFrame([{"code": "600000", "name": "浦发银行"}])

        with (
            patch("ztb_fetcher.utils.deepseek_ocr.get_config") as get_config,
            patch(
                "ztb_fetcher.utils.deepseek_ocr.request.urlopen",
                return_value=_FakeHTTPResponse(
                    {"choices": [{"message": {"content": "not json"}}]}
                ),
            ),
            patch.dict(os.environ, {"MOONSHOT_API_KEY": "test-key"}, clear=True),
        ):
            get_config.side_effect = lambda key, default=None: {
                "kimi_model": "kimi-k2.5",
                "kimi_base_url": "https://api.moonshot.cn/v1",
            }.get(key, default)
            with self.assertRaisesRegex(DeepSeekOCRError, "模型未返回有效 JSON"):
                extract_summary_stock_categories_from_image(
                    b"fake", "image/png", stocks_df, "20260415"
                )

    def test_extract_summary_stock_categories_from_image_raises_http_error(self):
        stocks_df = pd.DataFrame([{"code": "600000", "name": "浦发银行"}])

        with (
            patch("ztb_fetcher.utils.deepseek_ocr.get_config") as get_config,
            patch(
                "ztb_fetcher.utils.deepseek_ocr.request.urlopen",
                side_effect=error.HTTPError(
                    url="https://api.moonshot.cn/v1/chat/completions",
                    code=500,
                    msg="boom",
                    hdrs=None,
                    fp=None,
                ),
            ),
            patch.dict(os.environ, {"MOONSHOT_API_KEY": "test-key"}, clear=True),
        ):
            get_config.side_effect = lambda key, default=None: {
                "kimi_base_url": "https://api.moonshot.cn/v1",
                "kimi_model": "kimi-k2.5",
            }.get(key, default)
            with self.assertRaisesRegex(DeepSeekOCRError, "Kimi 图片结构化 HTTP 500"):
                extract_summary_stock_categories_from_image(
                    b"fake", "image/png", stocks_df, "20260415"
                )

    def test_extract_summary_stock_categories_from_image_raises_timeout_error(self):
        stocks_df = pd.DataFrame([{"code": "600000", "name": "浦发银行"}])

        with (
            patch("ztb_fetcher.utils.deepseek_ocr.get_config") as get_config,
            patch("ztb_fetcher.utils.deepseek_ocr.request.urlopen") as urlopen,
            patch.dict(os.environ, {"MOONSHOT_API_KEY": "test-key"}, clear=True),
        ):
            urlopen.side_effect = socket.timeout("timed out")
            get_config.side_effect = lambda key, default=None: {
                "kimi_base_url": "https://api.moonshot.cn/v1",
                "kimi_model": "kimi-k2.5",
            }.get(key, default)
            with self.assertRaisesRegex(DeepSeekOCRError, "Kimi 图片结构化 网络错误: timed out"):
                extract_summary_stock_categories_from_image(
                    b"fake", "image/png", stocks_df, "20260415"
                )


if __name__ == "__main__":
    unittest.main()
