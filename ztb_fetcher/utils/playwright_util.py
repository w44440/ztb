"""Playwright 工具模块"""

import logging
from functools import partial
from typing import Callable

from playwright.sync_api import Page, sync_playwright

from ztb_fetcher.utils.error_handler import PlaywrightBrowserError, PlaywrightNavigationError

logger = logging.getLogger(__name__)

# CDP 连接地址
CDP_URL = "http://localhost:9222"


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


def get_data_cdp(url: str, fetch_func: Callable, check_login_func: Callable = None) -> list:
    """使用 CDP 模式连接本地 Chrome 获取数据

    Args:
        url: 目标 URL
        fetch_func: 获取数据的函数，接收 page 参数
        check_login_func: 检查登录状态的函数

    Returns:
        获取的数据列表
    """
    with sync_playwright() as p:
        # 通过 CDP 连接本地 Chrome
        try:
            browser = p.chromium.connect_over_cdp(CDP_URL)
            logger.info(f"[CDP] 成功连接到 {CDP_URL}")
        except Exception as e:
            raise PlaywrightBrowserError(f"CDP 连接失败: {e}")

        try:
            # 使用默认上下文或获取现有页面
            contexts = browser.contexts
            if contexts:
                context = contexts[0]
            else:
                context = browser.new_context()

            pages = context.pages
            if pages:
                page = pages[0]
            else:
                page = context.new_page()

            # 访问页面
            try:
                page.goto(url, timeout=30000)
                page.wait_for_load_state("networkidle", timeout=30000)
            except Exception as e:
                raise PlaywrightNavigationError(f"页面导航失败: {e}")

            # 检查登录状态
            if check_login_func and not check_login_func(page):
                from ztb_fetcher.utils.error_handler import PlaywrightAuthError

                raise PlaywrightAuthError("页面需要登录")

            # 执行数据获取
            result = fetch_func(page)
            return result

        finally:
            # CDP 模式下不关闭浏览器，只关闭连接
            browser.close()
