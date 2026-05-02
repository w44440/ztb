"""JYGS website storage state management."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Callable

from playwright.sync_api import Page, sync_playwright

from web_state_store.s3 import S3Config, S3StateClient, StateStoreError

JYGS_BASE_URL = "https://www.jiuyangongshe.com/"
DEFAULT_OBJECT_KEY = "jygs_state.json"


def get_state_path() -> Path:
    configured = os.getenv("ZTB_JYGS_AUTH_STATE_PATH")
    if configured:
        return Path(configured).expanduser()
    data_root = Path(os.getenv("ZTB_DATA_ROOT", "/data/ops-data/ztb")).expanduser()
    return data_root / "auth" / "jygs_storage_state.json"


def ensure_state(site: str = "jygs") -> Path:
    _ensure_site(site)
    path = download_state(site)
    check_state(site, path=path)
    return path


def download_state(site: str = "jygs", path: Path | None = None) -> Path:
    _ensure_site(site)
    target = path or get_state_path()
    client = S3StateClient(S3Config.from_env(DEFAULT_OBJECT_KEY))
    return client.download_file(target)


def upload_state(site: str = "jygs", path: Path | None = None) -> None:
    _ensure_site(site)
    source = path or get_state_path()
    check_state(site, path=source)
    client = S3StateClient(S3Config.from_env(DEFAULT_OBJECT_KEY))
    client.upload_file(source)


def capture_state(
    site: str = "jygs",
    path: Path | None = None,
    login_timeout_seconds: int = 600,
    check_login_func: Callable[[Page], bool] | None = None,
) -> Path:
    _ensure_site(site)
    target = path or get_state_path()
    check_login = check_login_func or _check_jygs_login
    deadline = time.time() + login_timeout_seconds

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        try:
            context = browser.new_context(viewport={"width": 1920, "height": 1080})
            page = context.new_page()
            page.goto(JYGS_BASE_URL, timeout=30000)
            page.wait_for_load_state("networkidle", timeout=30000)

            if not check_login(page):
                while time.time() < deadline:
                    if check_login(page):
                        break
                    page.wait_for_timeout(1000)
                else:
                    raise StateStoreError("JYGS 登录超时")

            target.parent.mkdir(parents=True, exist_ok=True)
            context.storage_state(path=str(target))
            return target
        finally:
            browser.close()


def check_state(site: str = "jygs", path: Path | None = None) -> bool:
    _ensure_site(site)
    state_path = path or get_state_path()
    if not state_path.exists():
        raise StateStoreError(f"JYGS 状态文件不存在: {state_path}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context(
                storage_state=str(state_path),
                viewport={"width": 1920, "height": 1080},
            )
            page = context.new_page()
            page.goto(JYGS_BASE_URL, timeout=30000)
            page.wait_for_load_state("networkidle", timeout=30000)
            if not _check_jygs_login(page):
                raise StateStoreError("JYGS 状态文件无效或已过期")
            return True
        finally:
            browser.close()


def _ensure_site(site: str) -> None:
    if site != "jygs":
        raise StateStoreError(f"不支持的网站状态: {site}")


def _check_jygs_login(page: Page) -> bool:
    try:
        page.wait_for_load_state("networkidle")
        login_markers = [
            page.get_by_text("登录").first,
            page.get_by_text("注册").first,
            page.locator('button:has-text("登录")').first,
            page.locator('a:has-text("登录")').first,
            page.locator('a:has-text("注册")').first,
        ]
        for locator in login_markers:
            try:
                if locator.is_visible(timeout=1000):
                    return False
            except Exception:
                continue

        cookies = page.context.cookies([JYGS_BASE_URL])
        for cookie in cookies:
            name = str(cookie.get("name") or "")
            if not name:
                continue
            if name in {"HMACCOUNT", "time"}:
                continue
            if any(name.startswith(prefix) for prefix in ("Hm_",)):
                continue
            return True
        return False
    except Exception:
        return False
