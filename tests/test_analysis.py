import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pandas as pd

from ztb_fetcher.analysis import _format_topic_bar_label, build_daily_hot_topics, generate_report


class AnalysisTest(unittest.TestCase):
    def test_format_topic_bar_label_displays_both_counts(self):
        self.assertEqual(_format_topic_bar_label(24, 14), "24次 / 14只")

    def test_build_daily_hot_topics_returns_summary_and_stocks(self):
        reasons_df = pd.DataFrame(
            [
                {
                    "code": "000001",
                    "name": "平安银行",
                    "cate": "固态电池",
                    "reason": "固态电池 储能",
                },
                {"code": "000002", "name": "万科A", "cate": "固态电池", "reason": "新能源"},
            ]
        )

        summary_df, stock_df = build_daily_hot_topics(reasons_df)

        self.assertEqual(summary_df.iloc[0]["关键词"], "固态电池")
        self.assertEqual(int(summary_df.iloc[0]["出现次数"]), 2)
        self.assertEqual(int(summary_df.iloc[0]["涉及股票数"]), 2)
        self.assertEqual(len(stock_df[stock_df["关键词"] == "固态电池"]), 2)

    def test_generate_report_uses_single_day_hot_topics(self):
        class StubDB:
            def __init__(self):
                self.requested_date = None

            def query_lianban_stats(self, date_val, days):
                return pd.DataFrame()

            def query_daily_count_with_ma(self, date_val, days):
                return pd.DataFrame()

            def get_hot_topics_by_date(self, date_val):
                self.requested_date = date_val
                return pd.DataFrame(
                    [
                        {
                            "date": date_val,
                            "topic": f"题材{i}",
                            "appearance_count": 20 - i,
                            "stock_count": 10 - (i % 3),
                            "sample_stocks": "样例A、样例B",
                            "rank": i,
                        }
                        for i in range(1, 13)
                    ]
                )

            def query_zt_reasons(self, date_val=None):
                raise AssertionError("unexpected fallback")

        stub_db = StubDB()
        captured = {}

        with TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "20260416.png"

            def _fake_plot(lianban_df, trend_df, keywords_df, date_str, path):
                captured["keywords_df"] = keywords_df.copy()
                captured["path"] = path

            with (
                patch("ztb_fetcher.analysis.REPORTS_DIR", Path(tmp_dir)),
                patch("ztb_fetcher.analysis._plot_report", side_effect=_fake_plot),
            ):
                result = generate_report(stub_db, "20260416", days=10)

        self.assertEqual(str(stub_db.requested_date), "2026-04-16")
        self.assertEqual(len(captured["keywords_df"]), 10)
        self.assertEqual(captured["keywords_df"]["关键词"].tolist()[0], "题材1")
        self.assertEqual(captured["keywords_df"]["关键词"].tolist()[-1], "题材10")
        self.assertEqual(captured["path"], output_path)
        self.assertEqual(result, output_path)

    def test_generate_report_fallback_uses_single_day_reasons(self):
        class StubDB:
            def __init__(self):
                self.requested_reason_date = None

            def query_lianban_stats(self, date_val, days):
                return pd.DataFrame()

            def query_daily_count_with_ma(self, date_val, days):
                return pd.DataFrame()

            def get_hot_topics_by_date(self, date_val):
                return pd.DataFrame()

            def query_zt_reasons(self, date_val=None):
                self.requested_reason_date = date_val
                return pd.DataFrame(
                    [
                        {
                            "date": date_val,
                            "code": "000001",
                            "name": "平安银行",
                            "cate": "固态电池",
                            "reason": "固态电池 储能",
                        }
                    ]
                )

        stub_db = StubDB()
        captured = {}

        with TemporaryDirectory() as tmp_dir:

            def _fake_plot(lianban_df, trend_df, keywords_df, date_str, path):
                captured["keywords_df"] = keywords_df.copy()

            with (
                patch("ztb_fetcher.analysis.REPORTS_DIR", Path(tmp_dir)),
                patch("ztb_fetcher.analysis._plot_report", side_effect=_fake_plot),
            ):
                generate_report(stub_db, "20260416", days=10)

        self.assertEqual(str(stub_db.requested_reason_date), "2026-04-16")
        self.assertIn("固态电池", captured["keywords_df"]["关键词"].tolist())


if __name__ == "__main__":
    unittest.main()
