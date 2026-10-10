import os
from typing import Any

os.environ.setdefault("PADDLE_PDX_DISABLE_PROGRESS_BAR", "True")

import json
from config import OCR_LANG, FAST_MODE, OCR_CONFIDENCE_REVIEW_THRESHOLD, OCR_DIR

import hashlib
from typing import Optional

_engine = None
_OCR_CACHE = {}


def get_file_hash(path_or_bytes) -> str:
    hasher = hashlib.md5()
    if isinstance(path_or_bytes, bytes):
        hasher.update(path_or_bytes)
    else:
        with open(path_or_bytes, "rb") as f:
            hasher.update(f.read())
    return hasher.hexdigest()


def build_engine(fast_mode=FAST_MODE):
    import pyclipper
    from paddleocr import PaddleOCR

    base_args = {"lang": OCR_LANG, "enable_mkldnn": False}
    if fast_mode:
        base_args["det_limit_side_len"] = 800
        base_args["cpu_threads"] = 4
        try:
            return PaddleOCR(
                **base_args,
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
            )
        except (TypeError, ValueError):
            pass
    return PaddleOCR(**base_args)


def get_engine():
    global _engine
    if _engine is None:
        _engine = build_engine()
    return _engine


def run_ocr(image_path: str, cache_key: Optional[str] = None) -> list[dict[str, Any]]:
    """Normalize PaddleOCR output across supported API variants."""
    if cache_key:
        if cache_key in _OCR_CACHE:
            return _OCR_CACHE[cache_key]
        disk_cache_file = OCR_DIR / f"{cache_key}.json"
        if disk_cache_file.exists():
            try:
                with open(disk_cache_file, "r", encoding="utf-8") as f:
                    cached_lines = json.load(f)
                    _OCR_CACHE[cache_key] = cached_lines
                    return cached_lines
            except Exception:
                pass

    engine = get_engine()
    lines = []

    try:
        results = engine.predict(image_path)
    except AttributeError:
        results = engine.ocr(image_path)

    for res in results:
        if res is None:
            continue
        if hasattr(res, "get") and res.get("rec_texts") is not None:
            texts = res.get("rec_texts", [])
            scores = res.get("rec_scores", [])
            polys = res.get("rec_polys") or res.get("dt_polys") or []
            for text, conf, poly in zip(texts, scores, polys):
                x, y = poly[0]
                lines.append({"text": str(text), "conf": float(conf), "x": float(x), "y": float(y)})
        else:
            for item in res:
                box, (text, conf) = item
                x, y = box[0]
                lines.append({"text": str(text), "conf": float(conf), "x": float(x), "y": float(y)})
                
    if cache_key:
        _OCR_CACHE[cache_key] = lines
        try:
            disk_cache_file = OCR_DIR / f"{cache_key}.json"
            disk_cache_file.parent.mkdir(parents=True, exist_ok=True)
            with open(disk_cache_file, "w", encoding="utf-8") as f:
                json.dump(lines, f)
        except Exception:
            pass
        
    return lines


def ocr_to_dataframe(lines, confidence_threshold=OCR_CONFIDENCE_REVIEW_THRESHOLD):
    import pandas as pd
    columns = ["text", "conf", "x", "y"]
    if not lines:
        return pd.DataFrame(columns=columns + ["needs_review"])
    df = pd.DataFrame(lines)[columns]
    df = df.sort_values(["y", "x"]).reset_index(drop=True)
    df["conf"] = df["conf"].round(3)
    df["needs_review"] = df["conf"] < confidence_threshold
    return df
