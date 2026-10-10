"""Signature and stamp region cropper for Surat Perintah (Sprint) documents.

Extracts a clean visual crop of the official approval block (Pengesahan:
Tanda tangan dan stempel basah) from PDF or image documents.
"""

from io import BytesIO
from pathlib import Path
import base64
import json
import re
from typing import Any, Dict, Optional, Union

from PIL import Image
from config import CROPS_DIR, OCR_DIR
from src.ocr.engine import get_file_hash


def pil_to_base64(img: Image.Image, format: str = "PNG") -> str:
    """Encodes a PIL Image to base64 string."""
    buffered = BytesIO()
    img.save(buffered, format=format)
    return base64.b64encode(buffered.getvalue()).decode("utf-8")


def crop_sprint_signature_stamp(
    path_or_img: Union[str, Path, Image.Image],
    page_idx: int = 0,
    render_scale: float = 2.0,
    ocr_scale: float = 1.5,
) -> Optional[Image.Image]:
    """Crops the signature and stamp area from a Surat Perintah document.

    Supports both PDF files (rendered via pypdfium2) and raw PIL Images.
    Uses OCR coordinates from cache if available to find anchors (Kepala RS,
    dr. ..., NIP/Mayor, date). Falls back to standard bottom-right signature quadrant.
    """
    pil_img: Optional[Image.Image] = None
    pdf_path: Optional[Path] = None

    if isinstance(path_or_img, Image.Image):
        pil_img = path_or_img
    else:
        file_path = Path(path_or_img)
        if not file_path.exists():
            return None

        if file_path.suffix.lower() == ".pdf":
            import pypdfium2 as pdfium
            pdf_path = file_path
            doc = pdfium.PdfDocument(str(file_path))
            if len(doc) == 0:
                return None
            actual_idx = min(page_idx, len(doc) - 1)
            page = doc[actual_idx]
            pil_img = page.render(scale=render_scale).to_pil()
            doc.close()
        else:
            try:
                pil_img = Image.open(str(file_path)).convert("RGB")
            except Exception:
                return None

    if pil_img is None:
        return None

    w, h = pil_img.size

    # Attempt to use OCR cache anchors if PDF path is provided
    lines = []
    if pdf_path is not None:
        file_hash = get_file_hash(str(pdf_path))
        cache_file = OCR_DIR / f"{file_hash}_page_{page_idx}.json"
        if cache_file.exists():
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    lines = json.load(f)
            except Exception:
                pass

    coord_ratio = render_scale / ocr_scale if (pdf_path and ocr_scale > 0) else 1.0

    # Search for signature and stamp anchor lines in the bottom half of the page
    sig_lines = []
    for l in lines:
        y_val = l.get("y", 0) * coord_ratio
        if y_val < h * 0.45:
            continue
        txt = l.get("text", "")
        if any(re.search(pat, txt, re.I) for pat in [
            r"^(?:Kepala|Direktur|Komandan|Pimpinan|Karumkit)\b",
            r"\bdr\.?\s+[A-Za-z]",
            r"Sp\.[A-Za-z]+",
            r"(?:Mayor|Letkol|Kapten|Kolonel|PNS|NIP|NRP)\s*(?:Ckm|[0-9])",
            r"\b(?:Pekanbaru|Jakarta|Ditetapkan|Dikeluarkan)\b.*?\b20\d\d\b",
        ]):
            sig_lines.append(l)

    if sig_lines:
        xs = [l["x"] * coord_ratio for l in sig_lines]
        ys = [l["y"] * coord_ratio for l in sig_lines]
        min_x = min(xs)
        max_x = max(xs)
        min_y = min(ys)
        max_y = max(ys)

        # Padding: stamp sits on the left of or partly over the signature; text extends right
        crop_x1 = max(0, int(min_x - 140))
        crop_y1 = max(0, int(min_y - 45))
        crop_x2 = min(w, int(max_x + 360))
        crop_y2 = min(h, int(max_y + 45))
    else:
        # Standard fallback heuristic for Indonesian official documents:
        # bottom-right signature quadrant (y: 53%-88%, x: 48%-96%)
        crop_x1 = int(w * 0.48)
        crop_y1 = int(h * 0.53)
        crop_x2 = int(w * 0.96)
        crop_y2 = int(h * 0.88)

    # Ensure valid bounding box
    crop_x1 = max(0, min(crop_x1, w - 10))
    crop_y1 = max(0, min(crop_y1, h - 10))
    crop_x2 = max(crop_x1 + 10, min(crop_x2, w))
    crop_y2 = max(crop_y1 + 10, min(crop_y2, h))

    return pil_img.crop((crop_x1, crop_y1, crop_x2, crop_y2))


def crop_and_save_sprint_signature(
    path_or_img: Union[str, Path, Image.Image],
    page_idx: int = 0,
    output_dir: Optional[Path] = None,
) -> Optional[Dict[str, Any]]:
    """Crops the signature & stamp and saves to disk, returning path and base64."""
    cropped = crop_sprint_signature_stamp(path_or_img, page_idx=page_idx)
    if cropped is None:
        return None

    target_dir = output_dir or CROPS_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    if isinstance(path_or_img, (str, Path)):
        stem = Path(path_or_img).stem
    else:
        stem = "sprint"

    out_file = target_dir / f"{stem}_pengesahan_ttd_stempel.png"
    cropped.save(out_file, format="PNG")

    b64_str = pil_to_base64(cropped, format="PNG")

    return {
        "crop_path": str(out_file),
        "crop_base64": b64_str,
        "width": cropped.width,
        "height": cropped.height,
    }


def get_sprint_signature_preview(sp_doc: Optional[Dict[str, Any]]) -> Optional[str]:
    """Retrieves or dynamically generates the signature preview image for a Sprint doc.

    Returns a data URI string ('data:image/png;base64,...') or local file path.
    """
    if not sp_doc or not isinstance(sp_doc, dict):
        return None

    # 1. Direct base64 stored on document level
    b64 = sp_doc.get("signature_crop_base64")
    if b64:
        return f"data:image/png;base64,{b64}"

    # 2. Direct path stored on document level
    crop_path = sp_doc.get("signature_crop_path")
    if crop_path and Path(crop_path).exists():
        return str(crop_path)

    # 3. From fields.pengesahan
    p_f = sp_doc.get("fields", {}).get("pengesahan", {})
    if p_f.get("crop_base64"):
        return f"data:image/png;base64,{p_f['crop_base64']}"
    if p_f.get("crop_image") and Path(p_f["crop_image"]).exists():
        return str(p_f["crop_image"])

    # 4. On-the-fly crop if file_path exists on disk
    fpath = sp_doc.get("file_path")
    if fpath and Path(fpath).exists():
        try:
            sig_page = (p_f.get("page") or 1) - 1
            res = crop_and_save_sprint_signature(fpath, page_idx=sig_page)
            if res:
                return f"data:image/png;base64,{res['crop_base64']}"
        except Exception:
            pass

    return None
