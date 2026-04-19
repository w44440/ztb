import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd

from ztb_fetcher.ocr.local import LocalOCRError, extract_summary_stock_categories_from_image
from ztb_fetcher.ocr.structure import extract_stock_records


class OCRStructureTest(unittest.TestCase):
    def test_extract_stock_records_from_ths_summary_lines(self):
        lines = [
            "同花顺数据可视化",
            "金融科技：涨停个数 2",
            "09:30:00",
            "600000",
            "浦发银行",
            "000001",
            "平安银行",
            "其他概念",
            "300001",
            "特锐德",
            "相关个股非推荐，请勿据此买入，投资有风险，入市需谨慎",
        ]

        self.assertEqual(
            extract_stock_records(lines),
            [
                {"cate": "金融科技", "code": "600000", "name": "浦发银行"},
                {"cate": "金融科技", "code": "000001", "name": "平安银行"},
                {"cate": "其他概念", "code": "300001", "name": "特锐德"},
            ],
        )

    def test_extract_stock_records_supports_inline_code_and_name(self):
        lines = [
            "其他概念",
            "首板605298必得科技10:18:22轨交配套+业绩高增",
            "首板001330博纳影业13:48:09影视院线+AI短剧",
        ]

        self.assertEqual(
            extract_stock_records(lines),
            [
                {"cate": "其他概念", "code": "605298", "name": "必得科技"},
                {"cate": "其他概念", "code": "001330", "name": "博纳影业"},
            ],
        )


class LocalOCRTest(unittest.TestCase):
    def test_extract_summary_stock_categories_from_image_returns_structured_records(self):
        captured = {}
        stocks_df = pd.DataFrame([{"code": "600000", "name": "浦发银行"}])

        def fake_recognize_text(engine, image_path):
            captured["engine"] = engine
            captured["image_path"] = Path(image_path)
            self.assertEqual(captured["image_path"].read_bytes(), b"image")
            return ["金融：涨停个数 1", "600000", "浦发银行"]

        with (
            patch("ztb_fetcher.ocr.local.resolve_detection_limits", return_value=(4000, 4000)),
            patch("ztb_fetcher.ocr.local._build_engine", return_value=Mock(name="engine")),
            patch("ztb_fetcher.ocr.local.recognize_text", side_effect=fake_recognize_text),
        ):
            result = extract_summary_stock_categories_from_image(
                b"image", "image/png", stocks_df, "20260415"
            )

        self.assertEqual(result, [{"cate": "金融", "code": "600000", "name": "浦发银行"}])
        self.assertFalse(captured["image_path"].exists())

    def test_extract_summary_stock_categories_from_image_wraps_failures(self):
        with (
            patch("ztb_fetcher.ocr.local.resolve_detection_limits", return_value=(4000, 4000)),
            patch("ztb_fetcher.ocr.local._build_engine", side_effect=RuntimeError("boom")),
        ):
            with self.assertRaisesRegex(LocalOCRError, "本地 OCR 图片解析失败: boom"):
                extract_summary_stock_categories_from_image(
                    b"image", "image/png", pd.DataFrame(), "20260415"
                )


if __name__ == "__main__":
    unittest.main()
