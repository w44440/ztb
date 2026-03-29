"""错误处理模块"""


class FetcherError(Exception):
    """基础抓取错误"""
    pass


class PlaywrightError(FetcherError):
    """Playwright 相关错误"""
    pass


class PlaywrightBrowserError(PlaywrightError):
    """浏览器启动错误"""
    pass


class PlaywrightNavigationError(PlaywrightError):
    """页面导航错误"""
    pass


class PlaywrightAuthError(PlaywrightError):
    """登录认证错误"""
    pass
