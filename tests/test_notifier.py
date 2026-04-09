import base64
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ztb_fetcher.notifier import notify_fetch_result


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return b'{"errcode": 0, "errmsg": "ok"}'


class NotifierTest(unittest.TestCase):
    def test_no_webhook_skips_notification(self):
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("ztb_fetcher.notifier.request.urlopen") as urlopen,
        ):
            warnings = notify_fetch_result({"status": "ok", "date": "20260407"})

        self.assertEqual(warnings, [])
        urlopen.assert_not_called()

    def test_sends_markdown_and_image(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            image_path = Path(tmp_dir) / "report.png"
            image_bytes = b"fake png bytes"
            image_path.write_bytes(image_bytes)

            with (
                patch.dict(os.environ, {"ZTB_WECHAT_WEBHOOK": "https://example.com/webhook"}),
                patch(
                    "ztb_fetcher.notifier.request.urlopen",
                    return_value=FakeResponse(),
                ) as urlopen,
            ):
                warnings = notify_fetch_result(
                    {
                        "status": "ok",
                        "date": "20260407",
                        "is_trade_day": True,
                        "ths_count": 12,
                        "jygs_count": 8,
                        "report": str(image_path),
                        "warnings": [],
                        "error": None,
                    }
                )

        self.assertEqual(warnings, [])
        self.assertEqual(urlopen.call_count, 2)
        markdown_req = urlopen.call_args_list[0].args[0]
        image_req = urlopen.call_args_list[1].args[0]
        markdown_payload = json.loads(markdown_req.data.decode("utf-8"))
        image_payload = json.loads(image_req.data.decode("utf-8"))

        self.assertEqual(markdown_payload["msgtype"], "markdown")
        self.assertIn("涨停数据抓取完成", markdown_payload["markdown"]["content"])
        self.assertEqual(image_payload["msgtype"], "image")
        self.assertEqual(
            image_payload["image"]["base64"],
            base64.b64encode(image_bytes).decode("ascii"),
        )
        self.assertEqual(image_payload["image"]["md5"], hashlib.md5(image_bytes).hexdigest())

    def test_failure_result_sends_error_text_only(self):
        with (
            patch.dict(os.environ, {"ZTB_WECHAT_WEBHOOK": "https://example.com/webhook"}),
            patch("ztb_fetcher.notifier.request.urlopen", return_value=FakeResponse()) as urlopen,
        ):
            warnings = notify_fetch_result(
                {
                    "status": "error",
                    "date": "20260407",
                    "is_trade_day": True,
                    "ths_count": 0,
                    "jygs_count": 0,
                    "report": None,
                    "warnings": ["韭研公社抓取失败"],
                    "error": "同花顺抓取失败",
                }
            )

        self.assertEqual(warnings, [])
        self.assertEqual(urlopen.call_count, 1)
        req = urlopen.call_args.args[0]
        payload = json.loads(req.data.decode("utf-8"))
        self.assertIn("同花顺抓取失败", payload["markdown"]["content"])
        self.assertIn("韭研公社抓取失败", payload["markdown"]["content"])

    def test_wechat_error_returns_warning(self):
        class ErrorResponse(FakeResponse):
            def read(self):
                return b'{"errcode": 40001, "errmsg": "invalid credential"}'

        with (
            patch.dict(os.environ, {"ZTB_WECHAT_WEBHOOK": "https://example.com/webhook"}),
            patch("ztb_fetcher.notifier.request.urlopen", return_value=ErrorResponse()),
            patch("ztb_fetcher.notifier.logger.warning"),
        ):
            warnings = notify_fetch_result(
                {"status": "ok", "date": "20260407", "is_trade_day": True}
            )

        self.assertEqual(len(warnings), 1)
        self.assertIn("企业微信文本通知失败", warnings[0])

    def test_oversized_image_returns_warning_after_text(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            image_path = Path(tmp_dir) / "large.png"
            image_path.write_bytes(b"x" * (2 * 1024 * 1024 + 1))

            with (
                patch.dict(os.environ, {"ZTB_WECHAT_WEBHOOK": "https://example.com/webhook"}),
                patch(
                    "ztb_fetcher.notifier.request.urlopen",
                    return_value=FakeResponse(),
                ) as urlopen,
                patch("ztb_fetcher.notifier.logger.warning"),
            ):
                warnings = notify_fetch_result(
                    {
                        "status": "ok",
                        "date": "20260407",
                        "is_trade_day": True,
                        "report": str(image_path),
                    }
                )

        self.assertEqual(urlopen.call_count, 1)
        self.assertEqual(len(warnings), 1)
        self.assertIn("超过企业微信", warnings[0])


if __name__ == "__main__":
    unittest.main()
