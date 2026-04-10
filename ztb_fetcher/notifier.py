"""Fetch result notification helpers."""

import base64
import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Mapping
from urllib import error, request

from ztb_fetcher.config import get_config


logger = logging.getLogger(__name__)

WECHAT_IMAGE_SIZE_LIMIT = 2 * 1024 * 1024
HTTP_TIMEOUT_SECONDS = 30


class WeChatNotificationError(RuntimeError):
    """Raised when the WeChat robot API rejects a notification."""


def notify_fetch_result(result: Mapping[str, Any]) -> list[str]:
    """Send fetch result notification if the WeChat webhook is configured.

    Notification failures are returned as warning strings. They are not raised
    because push delivery should not affect the fetch outcome.
    """
    webhook = get_config("wechat_webhook")
    if not webhook:
        return []

    warnings = []

    try:
        _send_markdown(webhook, _build_markdown(result))
        logger.info("[Notifier] 企业微信文本通知已发送")
    except Exception as exc:  # noqa: BLE001 - keep fetch unaffected by push failures.
        warning = f"企业微信文本通知失败: {exc}"
        logger.warning(warning)
        warnings.append(warning)

    report = result.get("report")
    if report:
        try:
            _send_image(webhook, Path(str(report)))
            logger.info("[Notifier] 企业微信图片通知已发送")
        except Exception as exc:  # noqa: BLE001 - keep fetch unaffected by push failures.
            warning = f"企业微信图片通知失败: {exc}"
            logger.warning(warning)
            warnings.append(warning)

    return warnings


def _build_markdown(result: Mapping[str, Any]) -> str:
    status = str(result.get("status") or "unknown")
    date_str = str(result.get("date") or "-")
    title = {
        "ok": "涨停数据抓取完成",
        "partial": "涨停数据抓取部分完成",
        "error": "涨停数据抓取失败",
        "skipped": "涨停数据抓取跳过",
    }.get(status, "涨停数据抓取结果")

    lines = [
        f"## {title}",
        f"> 状态：{status}",
        f"> 日期：{date_str}",
        f"> 是否交易日：{'是' if result.get('is_trade_day') else '否'}",
        f"> 同花顺：{result.get('ths_count', 0)} 只",
        f"> 韭研公社：{result.get('jygs_count', 0)} 条",
    ]

    if result.get("report"):
        lines.append(f"> 报告：{result['report']}")

    if result.get("error"):
        lines.append(f"> 失败原因：{result['error']}")

    fetch_warnings = result.get("warnings") or []
    if fetch_warnings:
        lines.append("> 警告：")
        lines.extend(f"> - {item}" for item in fetch_warnings)

    return "\n".join(lines)


def _send_markdown(webhook: str, content: str) -> None:
    _post_json(
        webhook,
        {
            "msgtype": "markdown",
            "markdown": {
                "content": content,
            },
        },
    )


def _send_image(webhook: str, image_path: Path) -> None:
    if not image_path.exists():
        raise WeChatNotificationError(f"报告图片不存在: {image_path}")

    image_bytes = image_path.read_bytes()
    if len(image_bytes) > WECHAT_IMAGE_SIZE_LIMIT:
        limit_mb = WECHAT_IMAGE_SIZE_LIMIT // 1024 // 1024
        raise WeChatNotificationError(f"报告图片超过企业微信 {limit_mb}MB 限制: {image_path}")

    _post_json(
        webhook,
        {
            "msgtype": "image",
            "image": {
                "base64": base64.b64encode(image_bytes).decode("ascii"),
                "md5": hashlib.md5(image_bytes).hexdigest(),
            },
        },
    )


def _post_json(webhook: str, payload: Mapping[str, Any]) -> None:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        webhook,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
            response_body = resp.read().decode("utf-8")
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise WeChatNotificationError(f"HTTP {exc.code}: {body}") from exc
    except error.URLError as exc:
        raise WeChatNotificationError(str(exc.reason)) from exc

    try:
        response = json.loads(response_body) if response_body else {}
    except json.JSONDecodeError as exc:
        raise WeChatNotificationError(f"无法解析响应: {response_body}") from exc

    if response.get("errcode") != 0:
        raise WeChatNotificationError(
            f"errcode={response.get('errcode')}, errmsg={response.get('errmsg')}"
        )
