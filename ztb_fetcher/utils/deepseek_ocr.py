"""Kimi image structuring helpers."""

import base64
import json
import logging
import os
import socket
import time
from typing import Any
from urllib import error, request

import pandas as pd

from ztb_fetcher.config import get_config

logger = logging.getLogger(__name__)

DEFAULT_KIMI_TIMEOUT_SECONDS = 180


class DeepSeekOCRError(RuntimeError):
    """Raised when the OCR request fails or returns invalid content."""


def extract_summary_stock_categories_from_image(
    image_bytes: bytes,
    content_type: str,
    stocks_df: pd.DataFrame,
    date_str: str,
) -> list[dict[str, str]]:
    """Use Kimi 2.5 to read a THS summary image and return structured stock categories."""
    api_key, base_url, model, timeout_seconds = _get_kimi_request_config()
    endpoint = f"{base_url}/chat/completions"

    stock_rows = []
    if not stocks_df.empty:
        stock_rows = (
            stocks_df[["code", "name"]]
            .fillna("")
            .astype(str)
            .to_dict(orient="records")
        )

    payload = {
        "model": model,
        "thinking": {"type": "disabled"},
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是结构化解析助手。根据图片内容和候选股票列表，"
                    "提取可确认的股票 code、name、cate。"
                    "只输出 JSON 数组，每项必须包含 code、name、cate 三个字段。"
                    "优先参考候选股票列表中的 code 和 name。"
                    "无法确认的字段用空字符串，不要猜测，不要解释，不要输出 markdown。"
                ),
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": _build_image_data_url(image_bytes, content_type),
                        },
                    },
                    {
                        "type": "text",
                        "text": (
                            f"这是 {date_str} 的同花顺涨停分类图片，请直接识别并结构化输出股票分类。\n"
                            "返回 JSON 数组，每项格式为 "
                            '{"code":"600000","name":"浦发银行","cate":"金融"}。\n'
                            f"候选股票列表:\n{json.dumps(stock_rows, ensure_ascii=False)}"
                        ),
                    },
                ],
            },
        ],
    }
    logger.info(
        "[OCR] Kimi image structuring request: endpoint=%s model=%s timeout=%ss image_bytes=%s content_type=%s stock_candidates=%s date=%s",
        endpoint,
        model,
        timeout_seconds,
        len(image_bytes),
        content_type,
        len(stock_rows),
        date_str,
    )
    response_data = _post_json(
        endpoint,
        payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        error_prefix="Kimi 图片结构化",
        timeout_seconds=timeout_seconds,
    )

    content = _extract_message_content(response_data)
    try:
        raw_items = json.loads(_strip_code_fences(content))
    except json.JSONDecodeError as exc:
        raise DeepSeekOCRError(f"模型未返回有效 JSON: {content}") from exc

    if not isinstance(raw_items, list):
        raise DeepSeekOCRError(f"模型返回格式错误，应为 JSON 数组: {content}")

    normalized: list[dict[str, str]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code") or "").strip()
        name = str(item.get("name") or "").strip()
        cate = str(item.get("cate") or "").strip()
        if code and not (len(code) == 6 and code.isdigit()):
            code = ""
        if not code and not name:
            continue
        normalized.append({"code": code, "name": name, "cate": cate})

    logger.info("[OCR] Kimi image structuring response: rows=%s", len(normalized))
    return normalized


def _post_json(
    endpoint: str,
    payload: dict[str, Any],
    *,
    headers: dict[str, str],
    error_prefix: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    req = request.Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    start_time = time.monotonic()
    logger.info("[OCR] HTTP start: %s timeout=%ss", endpoint, timeout_seconds)
    try:
        with request.urlopen(req, timeout=timeout_seconds) as resp:
            body = resp.read().decode("utf-8")
        elapsed = time.monotonic() - start_time
        logger.info("[OCR] HTTP done: %s elapsed=%.2fs", endpoint, elapsed)
    except error.HTTPError as exc:
        elapsed = time.monotonic() - start_time
        response = exc.read().decode("utf-8", errors="replace")
        logger.warning("[OCR] HTTP error: %s elapsed=%.2fs status=%s", endpoint, elapsed, exc.code)
        raise DeepSeekOCRError(f"{error_prefix} HTTP {exc.code}: {response}") from exc
    except error.URLError as exc:
        elapsed = time.monotonic() - start_time
        logger.warning(
            "[OCR] URL error: %s elapsed=%.2fs reason=%s",
            endpoint,
            elapsed,
            exc.reason,
        )
        raise DeepSeekOCRError(f"{error_prefix} 网络错误: {exc.reason}") from exc
    except (TimeoutError, socket.timeout) as exc:
        elapsed = time.monotonic() - start_time
        logger.warning(
            "[OCR] Timeout: %s elapsed=%.2fs timeout=%ss error=%s",
            endpoint,
            elapsed,
            timeout_seconds,
            exc,
        )
        raise DeepSeekOCRError(f"{error_prefix} 网络错误: {exc}") from exc

    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise DeepSeekOCRError(f"{error_prefix} 无法解析响应 JSON: {body}") from exc


def _extract_message_content(response_data: dict[str, Any]) -> str:
    try:
        content = response_data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise DeepSeekOCRError(f"响应缺少 message content: {response_data}") from exc

    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text") or ""))
        return "".join(parts)
    raise DeepSeekOCRError(f"无法识别的 content 格式: {content}")


def _get_timeout_seconds(config_key: str, default: int) -> int:
    raw_value = get_config(config_key, default)
    try:
        timeout_seconds = int(raw_value)
    except (TypeError, ValueError):
        return default
    return timeout_seconds if timeout_seconds > 0 else default


def _get_kimi_request_config() -> tuple[str, str, str, int]:
    api_key = os.getenv("MOONSHOT_API_KEY")
    base_url = str(get_config("kimi_base_url", "https://api.moonshot.cn/v1")).rstrip("/")
    model = str(get_config("kimi_model", "kimi-k2.5")).strip()
    timeout_seconds = _get_timeout_seconds("kimi_timeout_seconds", DEFAULT_KIMI_TIMEOUT_SECONDS)

    if not api_key:
        raise DeepSeekOCRError("未配置 MOONSHOT_API_KEY")
    if not model:
        raise DeepSeekOCRError("未配置 kimi_model")

    return api_key, base_url, model, timeout_seconds


def _build_image_data_url(image_bytes: bytes, content_type: str) -> str:
    image_base64 = base64.b64encode(image_bytes).decode("ascii")
    normalized_content_type = str(content_type or "image/png").strip() or "image/png"
    return f"data:{normalized_content_type};base64,{image_base64}"


def _strip_code_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return stripped
