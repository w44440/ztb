import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd

from typer.testing import CliRunner

from ztb_fetcher.cli import app


class CliTest(unittest.TestCase):
    def setUp(self):
        self.runner = CliRunner()

    def test_agent_fetch_outputs_json_and_does_not_write_status(self):
        payload = {
            "command": "fetch",
            "status": "ok",
            "source": "all",
            "dates": ["20260407"],
            "results": [],
            "latest_trade_date": "20260407",
            "summary": {"requested_days": 1, "trade_days": 1, "ths_count": 12, "jygs_count": 8},
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            status_path = Path(tmp_dir) / "last_run.json"
            with (
                patch("ztb_fetcher.cli.Database"),
                patch("ztb_fetcher.cli.STATUS_FILE", status_path),
                patch("ztb_fetcher.cli._run_fetch_command", return_value=payload),
            ):
                result = self.runner.invoke(app, ["agent", "fetch", "--date", "20260407"])

        self.assertEqual(result.exit_code, 0)
        parsed = json.loads(result.stdout)
        self.assertEqual(parsed["command"], "agent.fetch")
        self.assertEqual(parsed["status"], "ok")
        self.assertFalse(status_path.exists())

    def test_agent_fetch_error_uses_nonzero_exit(self):
        payload = {
            "command": "fetch",
            "status": "error",
            "source": "all",
            "dates": ["20260407"],
            "results": [],
            "latest_trade_date": "20260407",
            "summary": {"requested_days": 1, "trade_days": 1, "ths_count": 0, "jygs_count": 0},
        }

        with (
            patch("ztb_fetcher.cli.Database"),
            patch("ztb_fetcher.cli._run_fetch_command", return_value=payload),
        ):
            result = self.runner.invoke(app, ["agent", "fetch", "--date", "20260407"])

        self.assertEqual(result.exit_code, 1)
        parsed = json.loads(result.stdout)
        self.assertEqual(parsed["status"], "error")

    def test_fetch_writes_partial_status_when_notify_warns(self):
        fetch_payload = {
            "command": "fetch",
            "status": "ok",
            "source": "all",
            "dates": ["20260407"],
            "latest_trade_date": "20260407",
            "summary": {"requested_days": 1, "trade_days": 1, "ths_count": 12, "jygs_count": 8},
            "results": [
                {
                    "date": "20260407",
                    "is_trade_day": True,
                    "status": "ok",
                    "ths": {"requested": True, "status": "ok", "count": 12, "error": None},
                    "jygs": {"requested": True, "status": "ok", "count": 8, "error": None},
                    "warnings": [],
                    "error": None,
                }
            ],
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            status_path = Path(tmp_dir) / "last_run.json"
            with (
                patch("ztb_fetcher.cli.Database"),
                patch("ztb_fetcher.cli.STATUS_FILE", status_path),
                patch("ztb_fetcher.cli._run_fetch_command", return_value=fetch_payload),
                patch("ztb_fetcher.cli.generate_report", return_value=Path(tmp_dir) / "report.png"),
                patch(
                    "ztb_fetcher.cli.notify_fetch_result",
                    return_value=["企业微信文本通知失败: invalid credential"],
                ),
            ):
                result = self.runner.invoke(app, ["fetch", "--date", "20260407"])

            status = json.loads(status_path.read_text(encoding="utf-8"))

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(status["status"], "partial")
        self.assertEqual(status["failed_stage"], "notify")
        self.assertEqual(status["report"], str(Path(tmp_dir) / "report.png"))
        self.assertIn("企业微信文本通知失败", status["warnings"][0])
        self.assertIn("推送企业微信", result.stdout)
        self.assertIn("企业微信文本通知失败", result.stdout)

    def test_fetch_writes_error_status_for_ths_failure(self):
        fetch_payload = {
            "command": "fetch",
            "status": "error",
            "source": "all",
            "dates": ["20260407"],
            "latest_trade_date": "20260407",
            "summary": {"requested_days": 1, "trade_days": 1, "ths_count": 0, "jygs_count": 0},
            "results": [
                {
                    "date": "20260407",
                    "is_trade_day": True,
                    "status": "error",
                    "ths": {
                        "requested": True,
                        "status": "error",
                        "count": 0,
                        "error": "同花顺抓取失败: timeout",
                    },
                    "jygs": {
                        "requested": True,
                        "status": "skipped",
                        "count": 0,
                        "error": "THS 无数据，跳过 JYGS",
                    },
                    "warnings": [],
                    "error": "同花顺抓取失败: timeout",
                }
            ],
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            status_path = Path(tmp_dir) / "last_run.json"
            with (
                patch("ztb_fetcher.cli.Database"),
                patch("ztb_fetcher.cli.STATUS_FILE", status_path),
                patch("ztb_fetcher.cli._run_fetch_command", return_value=fetch_payload),
                patch("ztb_fetcher.cli.generate_report") as generate_report,
                patch("ztb_fetcher.cli.notify_fetch_result", return_value=[]),
            ):
                result = self.runner.invoke(app, ["fetch", "--date", "20260407"])

            status = json.loads(status_path.read_text(encoding="utf-8"))

        self.assertEqual(result.exit_code, 1)
        self.assertEqual(status["status"], "error")
        self.assertEqual(status["failed_stage"], "ths")
        generate_report.assert_not_called()

    def test_run_single_fetch_marks_partial_when_ths_has_reconcile_warnings(self):
        from ztb_fetcher.cli import _run_single_fetch

        mock_db = Mock()
        mock_calendar = Mock()
        mock_calendar.is_trade_day.return_value = True
        mock_fetcher = Mock()
        mock_fetcher.fetch.return_value = (
            pd.DataFrame([{"code": "600000"}]),
            pd.DataFrame([{"code": "600000", "cate": "金融"}]),
        )
        mock_fetcher.last_fetch_metadata = {
            "warnings": ["THS 图片分类缺少代码: 000001"],
            "cate_count": 1,
        }

        with (
            patch("ztb_fetcher.cli.THSFetcher", return_value=mock_fetcher),
            patch("ztb_fetcher.cli._refresh_daily_hot_topics"),
        ):
            result = _run_single_fetch(mock_db, mock_calendar, "20260415", "ths")

        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["ths"]["cate_count"], 1)
        self.assertIn("THS 图片分类缺少代码", result["warnings"][0])

    def test_run_single_fetch_warns_when_jygs_returns_empty(self):
        from ztb_fetcher.cli import _run_single_fetch

        mock_db = Mock()
        mock_calendar = Mock()
        mock_calendar.is_trade_day.return_value = True
        mock_ths_fetcher = Mock()
        mock_ths_fetcher.fetch.return_value = (
            pd.DataFrame([{"code": "600000"}]),
            pd.DataFrame([{"code": "600000", "cate": "金融"}]),
        )
        mock_ths_fetcher.last_fetch_metadata = {"warnings": [], "cate_count": 1}
        mock_jygs_fetcher = Mock()
        mock_jygs_fetcher.fetch.return_value = pd.DataFrame()

        with (
            patch("ztb_fetcher.cli.THSFetcher", return_value=mock_ths_fetcher),
            patch("ztb_fetcher.cli.JYGSFetcher", return_value=mock_jygs_fetcher),
            patch("ztb_fetcher.cli._refresh_daily_hot_topics"),
        ):
            result = _run_single_fetch(mock_db, mock_calendar, "20260415", "all")

        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["jygs"]["status"], "error")
        self.assertIn("请先运行 `ztb login`", result["warnings"][0])

    def test_login_captures_storage_state(self):
        with patch("ztb_fetcher.cli.capture_state") as capture_state:
            result = self.runner.invoke(app, ["login"])

        self.assertEqual(result.exit_code, 0)
        capture_state.assert_called_once()
        self.assertIn("登录状态文件已保存", result.stdout)

    def test_login_returns_nonzero_when_login_fails(self):
        with patch("ztb_fetcher.cli.capture_state", side_effect=RuntimeError("boom")):
            result = self.runner.invoke(app, ["login"])

        self.assertEqual(result.exit_code, 1)
        self.assertIn("登录失败", result.stdout)

    def test_auth_upload_jygs_state_invokes_state_store(self):
        with patch("ztb_fetcher.cli.upload_state") as upload_state:
            result = self.runner.invoke(app, ["auth", "upload-jygs-state"])

        self.assertEqual(result.exit_code, 0)
        upload_state.assert_called_once_with("jygs")

    def test_auth_download_jygs_state_invokes_state_store(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_path = Path(tmp_dir) / "state.json"
            with (
                patch("ztb_fetcher.cli.download_state", return_value=state_path) as download_state,
                patch("ztb_fetcher.cli.check_state") as check_state,
            ):
                result = self.runner.invoke(app, ["auth", "download-jygs-state"])

        self.assertEqual(result.exit_code, 0)
        download_state.assert_called_once_with("jygs")
        check_state.assert_called_once_with("jygs", path=state_path)

    def test_auth_check_jygs_state_invokes_state_store(self):
        with patch("ztb_fetcher.cli.check_state") as check_state:
            result = self.runner.invoke(app, ["auth", "check-jygs-state"])

        self.assertEqual(result.exit_code, 0)
        check_state.assert_called_once_with("jygs")

    def test_history_uses_latest_hot_topic_by_default(self):
        mock_db = Mock()
        mock_db.get_latest_hot_topic_date.return_value = "2026-04-07"
        mock_db.get_hot_topics_by_date.return_value = pd.DataFrame(
            [
                {
                    "date": "2026-04-07",
                    "topic": "固态电池",
                    "appearance_count": 24,
                    "stock_count": 14,
                    "sample_stocks": "A、B",
                    "rank": 1,
                }
            ]
        )
        mock_db.get_previous_hot_topic_occurrence.return_value = pd.DataFrame(
            [
                {
                    "date": "2026-04-03",
                    "topic": "固态电池",
                    "appearance_count": 10,
                    "stock_count": 5,
                    "sample_stocks": "C",
                    "rank": 1,
                }
            ]
        )
        mock_db.get_hot_topic_stocks.side_effect = [
            pd.DataFrame([{"name": "德福科技"}, {"name": "上海洗霸"}]),
            pd.DataFrame([{"name": "领湃科技"}]),
        ]

        with patch("ztb_fetcher.cli.Database", return_value=mock_db):
            result = self.runner.invoke(app, ["history"])

        self.assertEqual(result.exit_code, 0)
        self.assertIn("固态电池", result.stdout)
        self.assertIn("2026-04-03", result.stdout)
        self.assertIn("德福科技", result.stdout)

    def test_history_topic_falls_back_to_latest_occurrence(self):
        mock_db = Mock()
        mock_db.get_latest_hot_topic_date.return_value = "2026-04-07"
        mock_db.get_hot_topic_by_date.return_value = pd.DataFrame()
        mock_db.get_latest_hot_topic_occurrence.return_value = pd.DataFrame(
            [
                {
                    "date": "2026-04-02",
                    "topic": "固态电池",
                    "appearance_count": 12,
                    "stock_count": 6,
                    "sample_stocks": "C",
                    "rank": 1,
                }
            ]
        )
        mock_db.get_previous_hot_topic_occurrence.return_value = pd.DataFrame()
        mock_db.get_hot_topic_stocks.return_value = pd.DataFrame([{"name": "领湃科技"}])

        with patch("ztb_fetcher.cli.Database", return_value=mock_db):
            result = self.runner.invoke(app, ["history", "-p", "固态电池"])

        self.assertEqual(result.exit_code, 0)
        self.assertIn("当日未出现", result.stdout)
        self.assertIn("2026-04-02", result.stdout)

    def test_backfill_topics_rebuilds_all_reason_dates(self):
        mock_db = Mock()
        mock_db.get_reason_dates.return_value = [
            pd.Timestamp("2026-04-01").date(),
            pd.Timestamp("2026-04-02").date(),
        ]

        with (
            patch("ztb_fetcher.cli.Database", return_value=mock_db),
            patch("ztb_fetcher.cli._refresh_daily_hot_topics") as refresh_daily_hot_topics,
        ):
            result = self.runner.invoke(app, ["backfill-topics"])

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(refresh_daily_hot_topics.call_count, 2)
        self.assertIn("已处理 2/2 天", result.stdout)

    def test_backfill_topics_returns_nonzero_on_partial_failure(self):
        mock_db = Mock()
        mock_db.get_reason_dates.return_value = [
            pd.Timestamp("2026-04-01").date(),
            pd.Timestamp("2026-04-02").date(),
        ]

        def _side_effect(_db, date_str):
            if date_str == "20260402":
                raise RuntimeError("boom")

        with (
            patch("ztb_fetcher.cli.Database", return_value=mock_db),
            patch("ztb_fetcher.cli._refresh_daily_hot_topics", side_effect=_side_effect),
        ):
            result = self.runner.invoke(app, ["backfill-topics"])

        self.assertEqual(result.exit_code, 1)
        self.assertIn("20260402", result.stdout)


if __name__ == "__main__":
    unittest.main()
