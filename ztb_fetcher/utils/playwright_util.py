"""Playwright 工具模块."""

from pathlib import Path
from typing import Callable

from playwright.sync_api import Browser, BrowserContext, Playwright, sync_playwright

from ztb_fetcher.config import get_config
from ztb_fetcher.utils.error_handler import (
    PlaywrightAuthError,
    PlaywrightBrowserError,
    PlaywrightNavigationError,
)

DEFAULT_VIEWPORT = {"width": 1920, "height": 1080}
DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


def get_data(url: str, fetch_func: Callable, check_login_func: Callable = None) -> list:
    """使用 Playwright 获取数据

    Args:
        url: 目标 URL
        fetch_func: 获取数据的函数，接收 page 参数
        check_login_func: 检查登录状态的函数

    Returns:
        获取的数据列表
    """
    with sync_playwright() as p:
        # 启动浏览器
        try:
            browser = p.chromium.launch(headless=True)
        except Exception as e:
            raise PlaywrightBrowserError(f"浏览器启动失败: {e}")

        try:
            context = browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            )
            page = context.new_page()

            # 访问页面
            try:
                page.goto(url, timeout=30000)
                page.wait_for_load_state("networkidle", timeout=30000)
            except Exception as e:
                raise PlaywrightNavigationError(f"页面导航失败: {e}")

            # 检查登录状态
            if check_login_func and not check_login_func(page):
                from utils.error_handler import PlaywrightAuthError

                raise PlaywrightAuthError("页面需要登录")

            # 执行数据获取
            result = fetch_func(page)
            return result

        finally:
            browser.close()


def _parse_bool(value: str | bool | None, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value

    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _get_page(context: BrowserContext):
    pages = context.pages
    return pages[0] if pages else context.new_page()


def _launch_browser(playwright: Playwright, headless: bool) -> Browser:
    try:
        return playwright.chromium.launch(headless=headless)
    except Exception as e:
        raise PlaywrightBrowserError(f"浏览器启动失败: {e}")


def get_data_with_storage_state(
    url: str,
    fetch_func: Callable,
    storage_state_path: Path,
    check_login_func: Callable | None = None,
) -> list:
    """使用 Playwright storage_state 获取数据。"""
    headless = _parse_bool(get_config("jygs_headless"), default=True)

    with sync_playwright() as p:
        browser = _launch_browser(p, headless=headless)
        try:
            context = browser.new_context(
                storage_state=str(storage_state_path),
                viewport=DEFAULT_VIEWPORT,
                user_agent=DEFAULT_USER_AGENT,
            )
            page = _get_page(context)

            try:
                page.goto(url, timeout=30000)
                page.wait_for_load_state("networkidle", timeout=30000)
            except Exception as e:
                raise PlaywrightNavigationError(f"页面导航失败: {e}")

            if check_login_func and not check_login_func(page):
                raise PlaywrightAuthError("JYGS 状态文件无效或已过期")

            return fetch_func(page)
        finally:
            browser.close()
