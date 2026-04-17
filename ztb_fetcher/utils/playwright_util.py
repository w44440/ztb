"""Playwright 工具模块."""

import logging
import time
from pathlib import Path
from typing import Callable

from playwright.sync_api import BrowserContext, Playwright, sync_playwright

from ztb_fetcher.config import JYGS_USER_DATA_DIR, get_config
from ztb_fetcher.utils.error_handler import (
    PlaywrightAuthError,
    PlaywrightBrowserError,
    PlaywrightNavigationError,
)

logger = logging.getLogger(__name__)

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


def _resolve_user_data_dir() -> Path:
    configured_dir = get_config("jygs_user_data_dir")
    user_data_dir = Path(configured_dir).expanduser() if configured_dir else JYGS_USER_DATA_DIR
    user_data_dir.mkdir(parents=True, exist_ok=True)
    return user_data_dir


def _launch_persistent_context(playwright: Playwright, headless: bool) -> BrowserContext:
    user_data_dir = _resolve_user_data_dir()
    try:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(user_data_dir),
            headless=headless,
            viewport=DEFAULT_VIEWPORT,
            user_agent=DEFAULT_USER_AGENT,
        )
    except Exception as e:
        raise PlaywrightBrowserError(f"浏览器启动失败: {e}")

    logger.info("[Playwright] 已启动持久化上下文: %s", user_data_dir)
    return context


def _get_page(context: BrowserContext):
    pages = context.pages
    return pages[0] if pages else context.new_page()


def get_data_persistent(url: str, fetch_func: Callable, check_login_func: Callable = None) -> list:
    """使用 Playwright 持久化上下文获取数据。

    Args:
        url: 目标 URL
        fetch_func: 获取数据的函数，接收 page 参数
        check_login_func: 检查登录状态的函数

    Returns:
        获取的数据列表
    """
    headless = _parse_bool(get_config("jygs_headless"), default=True)

    with sync_playwright() as p:
        context = _launch_persistent_context(p, headless=headless)
        try:
            page = _get_page(context)

            try:
                page.goto(url, timeout=30000)
                page.wait_for_load_state("networkidle", timeout=30000)
            except Exception as e:
                raise PlaywrightNavigationError(f"页面导航失败: {e}")

            if check_login_func and not check_login_func(page):
                raise PlaywrightAuthError("页面需要登录，请先运行 `ztb login`")

            return fetch_func(page)
        finally:
            context.close()


def ensure_logged_in(
    url: str,
    check_login_func: Callable,
    login_timeout_seconds: int = 300,
) -> None:
    """启动有头浏览器并等待用户手动完成登录。"""
    deadline = time.time() + login_timeout_seconds

    with sync_playwright() as p:
        context = _launch_persistent_context(p, headless=False)
        try:
            page = _get_page(context)

            try:
                page.goto(url, timeout=30000)
                page.wait_for_load_state("networkidle", timeout=30000)
            except Exception as e:
                raise PlaywrightNavigationError(f"页面导航失败: {e}")

            if check_login_func(page):
                logger.info("[Playwright] 检测到现有登录态，无需重复登录")
                return

            logger.info("[Playwright] 等待用户手动登录，超时时间 %s 秒", login_timeout_seconds)
            while time.time() < deadline:
                if check_login_func(page):
                    logger.info("[Playwright] 登录成功，状态已写入持久化目录")
                    return
                page.wait_for_timeout(1000)

            raise PlaywrightAuthError("登录超时，请重试 `ztb login`")
        finally:
            context.close()
