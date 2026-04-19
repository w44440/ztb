from __future__ import annotations

import re
from typing import Iterable

_CODE_RE = re.compile(r"^\d{6}$")
_TIME_RE = re.compile(r"^\d{2}:\d{2}:\d{2}$")
_INLINE_CODE_RE = re.compile(r"(?P<code>\d{6})(?P<tail>.+)")

_NOISE_EXACT = {
    "同花顺数",
    "同花顺数据可视化",
    "DATAVISUALIZATION/DATAVISUALIZATION",
    "TION/DATAVISUALIZATION/DATAVISUALIZATION",
    "Q热点复盘",
    "A股涨停复盘",
    "一字涨停",
    "T字涨停",
    "图片由AI生成",
    "相关个股非推荐，请勿据此买入，投资有风险，入市需谨慎",
    "可视模型：@同花顺数据可视化",
}

_NOISE_PREFIXES = (
    "涨停个数：",
    "总晋级率：",
    "总炸板率：",
    "总竞价涨幅：",
    "注：",
    "数据来源：",
    "可视模型：",
    "可视化",
    "据可视化",
)


def extract_stock_records(lines: Iterable[str]) -> list[dict[str, str]]:
    """Extract stock records from OCR lines.

    The target layout is:
    category title -> status line -> code -> stock name
    """
    records: list[dict[str, str]] = []
    current_category = ""
    pending_code = ""
    seen: set[tuple[str, str, str]] = set()

    for raw_line in lines:
        line = _normalize_line(raw_line)
        if not line or _is_noise(line):
            continue

        category = _parse_category(line)
        if category:
            current_category = category
            pending_code = ""
            continue

        if _is_code_line(line):
            pending_code = line
            continue

        inline_record = _parse_inline_record(line)
        if inline_record and current_category:
            code, name = inline_record
            key = (current_category, code, name)
            if key not in seen:
                seen.add(key)
                records.append({"cate": current_category, "code": code, "name": name})
            pending_code = ""
            continue

        if pending_code and current_category and _looks_like_stock_name(line):
            key = (current_category, pending_code, line)
            if key not in seen:
                seen.add(key)
                records.append({"cate": current_category, "code": pending_code, "name": line})
            pending_code = ""

    return records


def _normalize_line(line: str) -> str:
    return "".join(str(line).split())


def _parse_category(line: str) -> str:
    if line == "其他概念":
        return line
    if "：" not in line:
        return ""

    left, right = line.split("：", 1)
    if not left or not right:
        return ""
    if _is_noise(left) or _is_code_line(left) or _is_time_line(left):
        return ""
    if len(left) > 16 or any(ch.isdigit() for ch in left):
        return ""
    return left


def _parse_inline_record(line: str) -> tuple[str, str] | None:
    match = _INLINE_CODE_RE.search(line)
    if not match:
        return None

    code = match.group("code")
    name = _extract_inline_name(match.group("tail"))
    if not name or not _looks_like_stock_name(name):
        return None
    return code, name


def _extract_inline_name(text: str) -> str:
    text = re.split(r"\d{2}:\d{2}:\d{2}", text, maxsplit=1)[0]
    text = re.split(r"[+：:/\-]", text, maxsplit=1)[0]
    return text.strip()


def _is_noise(line: str) -> bool:
    return line in _NOISE_EXACT or any(line.startswith(prefix) for prefix in _NOISE_PREFIXES)


def _is_code_line(line: str) -> bool:
    return bool(_CODE_RE.match(line))


def _is_time_line(line: str) -> bool:
    return bool(_TIME_RE.match(line))


def _looks_like_stock_name(text: str) -> bool:
    if len(text) < 2 or len(text) > 12:
        return False
    if _is_code_line(text) or _is_time_line(text):
        return False
    if _is_noise(text):
        return False
    if any(ch in text for ch in {":", "：", "+", "/", "-", "（", "）", "(", ")", "。"}):
        return False
    return True
