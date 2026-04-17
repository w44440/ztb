import unittest
from unittest.mock import Mock

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


if __name__ == "__main__":
    unittest.main()
