from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
from PIL import Image

from .structure import extract_stock_records

logger = logging.getLogger(__name__)


class LocalOCRError(RuntimeError):
    """Raised when local PaddleOCR recognition or structuring fails."""


def extract_summary_stock_categories_from_image(
    image_bytes: bytes,
    content_type: str,
    stocks_df: pd.DataFrame,
    date_str: str,
) -> list[dict[str, str]]:
    """Recognize a THS summary image with local PaddleOCR and return stock categories."""
    del stocks_df

    suffix = _suffix_from_content_type(content_type)
    image_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f"ths_summary_{date_str}_", suffix=suffix, delete=False
        ) as tmp:
            tmp.write(image_bytes)
            image_path = Path(tmp.name)

        det_limit_side_len, _ = resolve_detection_limits(image_path, 4000)
        engine = _build_engine("ch", det_limit_side_len, "max")
        lines = recognize_text(engine, image_path)
        records = extract_stock_records(lines)
        logger.info(
            "[OCR] Local PaddleOCR summary structuring response: lines=%s rows=%s date=%s",
            len(lines),
            len(records),
            date_str,
        )
        return records
    except LocalOCRError:
        raise
    except Exception as exc:
        raise LocalOCRError(f"本地 OCR 图片解析失败: {exc}") from exc
    finally:
        if image_path is not None:
            image_path.unlink(missing_ok=True)


def _build_engine(lang: str, text_det_limit_side_len: int, text_det_limit_type: str) -> Any:
    try:
        from paddleocr import PaddleOCR
    except ImportError as exc:
        raise LocalOCRError(
            "PaddleOCR is not installed. Install paddlepaddle for your platform, "
            "then install paddleocr before retrying."
        ) from exc

    init_attempts = (
        {
            "lang": lang,
            "use_doc_orientation_classify": False,
            "use_doc_unwarping": False,
            "use_textline_orientation": False,
            "text_det_limit_side_len": text_det_limit_side_len,
            "text_det_limit_type": text_det_limit_type,
        },
        {
            "lang": lang,
            "text_det_limit_side_len": text_det_limit_side_len,
            "text_det_limit_type": text_det_limit_type,
        },
        {"lang": lang},
    )

    last_error: Exception | None = None
    for kwargs in init_attempts:
        try:
            return PaddleOCR(**kwargs)
        except TypeError as exc:
            last_error = exc

    raise LocalOCRError(f"Failed to initialize PaddleOCR: {last_error}") from last_error


def recognize_text(engine: Any, image_path: Path) -> list[str]:
    raw_result = engine.predict(str(image_path))

    texts = _extract_texts_from_prediction_result(raw_result)
    if texts:
        return texts

    lines = list(_iter_line_items(raw_result))
    lines.sort(key=_line_sort_key)
    return [text for _, text in (_extract_text(item) for item in lines) if text]


def resolve_detection_limits(image_path: Path, requested_limit: int) -> tuple[int, int]:
    with Image.open(image_path) as image:
        width, height = image.size

    longest_side = max(width, height, requested_limit)
    rounded_limit = ((longest_side + 31) // 32) * 32
    return rounded_limit, rounded_limit


def _iter_line_items(obj: Any) -> Iterable[Any]:
    if hasattr(obj, "json"):
        yield from _iter_line_items(getattr(obj, "json"))
        return

    if _looks_like_line_item(obj):
        yield obj
        return

    if isinstance(obj, dict):
        for value in obj.values():
            yield from _iter_line_items(value)
        return

    if isinstance(obj, (list, tuple)):
        for item in obj:
            yield from _iter_line_items(item)


def _extract_texts_from_prediction_result(raw_result: Any) -> list[str]:
    texts: list[str] = []

    if isinstance(raw_result, dict):
        candidates = [raw_result]
    elif isinstance(raw_result, (list, tuple)):
        candidates = list(raw_result)
    else:
        candidates = [raw_result]

    for item in candidates:
        if hasattr(item, "json"):
            item = item.json
        if isinstance(item, dict):
            res = item.get("res", item)
            if isinstance(res, dict):
                rec_texts = res.get("rec_texts")
                if isinstance(rec_texts, list):
                    texts.extend(str(text).strip() for text in rec_texts if str(text).strip())
                elif isinstance(rec_texts, str) and rec_texts.strip():
                    texts.append(rec_texts.strip())

    return texts


def _looks_like_line_item(obj: Any) -> bool:
    return (
        isinstance(obj, (list, tuple))
        and len(obj) >= 2
        and isinstance(obj[0], (list, tuple))
        and not _looks_like_line_item(obj[1])
    )


def _extract_text(item: Any) -> tuple[Any, str]:
    if isinstance(item, dict):
        box = item.get("box") or item.get("bbox") or item.get("points") or []
        text = item.get("text") or item.get("transcription") or ""
        return box, str(text)

    box = item[0] if item else []
    payload = item[1] if len(item) > 1 else ""

    if isinstance(payload, (list, tuple)):
        text = payload[0] if payload else ""
    else:
        text = payload

    if not isinstance(text, str):
        text = str(text)

    return box, text.strip()


def _line_sort_key(item: Any) -> tuple[float, float, float, float]:
    box, _ = _extract_text(item)
    points = list(_as_points(box))
    if not points:
        return (0.0, 0.0, 0.0, 0.0)

    xs = [x for x, _ in points]
    ys = [y for _, y in points]
    return (min(ys), min(xs), max(ys), max(xs))


def _as_points(box: Any) -> Iterable[tuple[float, float]]:
    if not isinstance(box, (list, tuple)):
        return []

    points: list[tuple[float, float]] = []
    for point in box:
        if isinstance(point, (list, tuple)) and len(point) >= 2:
            try:
                points.append((float(point[0]), float(point[1])))
            except (TypeError, ValueError):
                continue
    return points


def _suffix_from_content_type(content_type: str) -> str:
    content_type = content_type.lower().split(";", 1)[0].strip()
    return {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/bmp": ".bmp",
    }.get(content_type, ".png")
