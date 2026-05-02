import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd

from ztb_fetcher.fetchers.jygs_fetcher import JYGSFetcher


def _mock_locator(visible: bool) -> Mock:
    locator = Mock()
    locator.first = locator
    locator.is_visible.return_value = visible
    return locator


class JYGSFetcherTest(unittest.TestCase):
    def test_check_login_returns_false_with_only_analytics_cookies(self):
        page = Mock()
        page.wait_for_load_state.return_value = None
        page.get_by_text.side_effect = lambda _text: _mock_locator(False)
        page.locator.side_effect = lambda _selector: _mock_locator(False)
        page.context.cookies.return_value = [
            {"name": "Hm_lvt_abc"},
            {"name": "Hm_lpvt_abc"},
            {"name": "HMACCOUNT"},
            {"name": "time"},
        ]

        self.assertFalse(JYGSFetcher._check_login(page))

    def test_check_login_returns_true_with_non_analytics_cookie_and_no_login_entry(self):
        page = Mock()
        page.wait_for_load_state.return_value = None
        page.get_by_text.side_effect = lambda _text: _mock_locator(False)
        page.locator.side_effect = lambda _selector: _mock_locator(False)
        page.context.cookies.return_value = [
            {"name": "Hm_lvt_abc"},
            {"name": "sessionid"},
        ]

        self.assertTrue(JYGSFetcher._check_login(page))

    def test_fetch_uses_central_storage_state(self):
        db = Mock()
        fetcher = JYGSFetcher(db)
        state_path = Path("/tmp/jygs_state.json")

        with (
            patch("ztb_fetcher.fetchers.jygs_fetcher._cache.get", return_value=None),
            patch("ztb_fetcher.fetchers.jygs_fetcher._cache.set"),
            patch("ztb_fetcher.fetchers.jygs_fetcher.ensure_state", return_value=state_path) as ensure,
            patch(
                "ztb_fetcher.fetchers.jygs_fetcher.get_data_with_storage_state",
                return_value=["600000 浦发银行 金融 银行股涨停"],
            ) as get_data,
            patch.object(
                fetcher,
                "_parse_data",
                return_value=pd.DataFrame(
                    [{"date": "2026-04-15", "code": "600000", "name": "浦发银行"}]
                ),
            ),
        ):
            df = fetcher.fetch("20260415", filter_codes={"600000"})

        self.assertFalse(df.empty)
        ensure.assert_called_once_with("jygs")
        self.assertEqual(get_data.call_args.args[2], state_path)


if __name__ == "__main__":
    unittest.main()
