import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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


if __name__ == "__main__":
    unittest.main()
