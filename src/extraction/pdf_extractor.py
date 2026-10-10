import os
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import pdfplumber
import pypdfium2 as pdfium
from src.ocr.engine import run_ocr


def _cluster_ocr_lines(raw_lines: List[Dict[str, Any]], y_tol: float = 14.0) -> List[str]:
    """Clusters word/phrase OCR bounding boxes that lie on approximately the same vertical line."""
    if not raw_lines:
        return []
    sorted_items = sorted(raw_lines, key=lambda l: (l.get("y", 0), l.get("x", 0)))
    clusters: List[List[Dict[str, Any]]] = []
    current_cluster = [sorted_items[0]]
    current_y = sorted_items[0].get("y", 0)

    for item in sorted_items[1:]:
        y = item.get("y", 0)
        if abs(y - current_y) <= y_tol:
            current_cluster.append(item)
        else:
            clusters.append(current_cluster)
            current_cluster = [item]
            current_y = y
    if current_cluster:
        clusters.append(current_cluster)

    lines = []
    for cluster in clusters:
        cluster.sort(key=lambda l: l.get("x", 0))
        line_text = " ".join(str(c.get("text", "")).strip() for c in cluster if str(c.get("text", "")).strip())
        if line_text:
            lines.append(line_text)
    return lines


def _ocr_pdf_page(doc_pdfium: pdfium.PdfDocument, page_idx: int, path: Optional[str] = None) -> str:
    """Renders a PDF page to image and runs OCR with optimized 1.5 scale."""
    if page_idx >= len(doc_pdfium):
        return ""
    try:
        page = doc_pdfium[page_idx]
        image = page.render(scale=1.5).to_pil()
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            image.save(tmp_path)
            from src.ocr.engine import get_file_hash
            cache_key = get_file_hash(path) + f"_page_{page_idx}" if path else None
            raw_lines = run_ocr(tmp_path, cache_key=cache_key)
            clustered = _cluster_ocr_lines(raw_lines)
            return "\n".join(clustered)
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
    except Exception:
        return ""


def extract_pdf_tables(path, max_pages: Optional[int] = 5):
    """Extracts tables from a PDF up to max_pages to prevent heavy table scanning on large docs."""
    all_tables = []
    try:
        with pdfplumber.open(path) as pdf:
            page_slice = pdf.pages[:max_pages] if max_pages else pdf.pages
            for page_index, page in enumerate(page_slice):
                for table in page.extract_tables():
                    all_tables.append((page_index, table))
    except Exception:
        pass
    return all_tables


def extract_pdf_text(
    path,
    max_pages: Optional[int] = None,
    max_ocr_pages: int = 1,
    ocr_enabled: bool = True,
    doc_type: Optional[str] = None,
) -> List[str]:
    """Extracts text per page from PDF. If a page has sparse/scanned text or if it is a
    hybrid document missing crucial technical data, runs OCR specifically on that page
    up to max_ocr_pages and merges/substitutes as appropriate.
    """
    native_pages: List[str] = []
    try:
        with pdfplumber.open(path) as pdf:
            page_slice = pdf.pages[:max_pages] if max_pages else pdf.pages
            for page in page_slice:
                # Use y_tolerance=1.5 so tightly spaced certificate/card layouts don't collapse lines horizontally
                text = page.extract_text(y_tolerance=1.5) or page.extract_text() or ""
                native_pages.append(text)
    except Exception:
        pass

    if not ocr_enabled:
        return native_pages

    # 1. Check which early pages lack sufficient native text (purely scanned page or form image)
    sparse_indices = [
        idx for idx in range(min(len(native_pages), max_ocr_pages))
        if len(re.findall(r"[A-Za-z]", native_pages[idx])) < 20
    ]

    # 2. Smart hybrid check: pages with native text (e.g. digital header) but where tables
    # or equipment specifications are raster images (scanned tables)
    hybrid_indices = []
    for idx in range(min(len(native_pages), max_ocr_pages)):
        if idx in sparse_indices:
            continue
        p_text = native_pages[idx]
        is_tech_doc = (
            doc_type in {"uji_fungsi", "uji_kesesuaian", "paparan_radiasi"}
            or bool(re.search(r"\b(?:FUNCTIONAL\s+TEST|UJI\s+FUNGSI|ACCEPTANCE\s+TEST|UJI\s+KESESUAIAN|PAPARAN\s+RADIASI)\b", p_text, re.I))
        )
        if is_tech_doc:
            has_serial_keyword = bool(re.search(r"\b(?:Serial\s*No|Nomor\s*seri|No\.?\s*Seri|S/N|SN[:\s]|Serial\s+Number)\b", p_text, re.I))
            has_serial_val = bool(re.search(r"\b(?:SB[0-9]{5,}|[A-Z0-9]{7,}|20G[0-9]{3,}|\b\d{5,}\b)\b", p_text))
            # If native text does not have both serial keyword and actual serial number value,
            # the table is likely a scanned image requiring OCR merge
            if not (has_serial_keyword and has_serial_val):
                hybrid_indices.append(idx)

    target_ocr_indices = sparse_indices + hybrid_indices
    if not target_ocr_indices:
        return native_pages

    # Only open PDFium if there is actually a scanned/sparse or hybrid page that requires OCR
    doc_pdfium = None
    try:
        doc_pdfium = pdfium.PdfDocument(str(path))
        total_pages = len(doc_pdfium)
        if max_pages:
            total_pages = min(total_pages, max_pages)
    except Exception:
        total_pages = len(native_pages)

    pages: List[str] = list(native_pages)
    while len(pages) < total_pages:
        pages.append("")

    try:
        for idx in target_ocr_indices:
            if idx < total_pages and doc_pdfium is not None:
                ocr_text = _ocr_pdf_page(doc_pdfium, idx, str(path))
                if ocr_text:
                    if idx in sparse_indices:
                        pages[idx] = ocr_text
                    else:
                        # Hybrid page: Merge native digital text with OCR text so both header and scanned table are preserved
                        pages[idx] = f"{pages[idx]}\n\n--- OCR EXTRACTED CONTENT ---\n{ocr_text}"
    finally:
        if doc_pdfium is not None:
            try:
                doc_pdfium.close()
            except Exception:
                pass

    return pages


def extract_pdf_document(
    path,
    need_tables: bool = True,
    max_pages: Optional[int] = None,
    max_table_pages: Optional[int] = 5,
    max_ocr_pages: int = 1,
    ocr_enabled: bool = True,
    doc_type: Optional[str] = None,
):
    """Extracts full document text and tables with selective page scanning for high performance."""
    pages_text = extract_pdf_text(
        path,
        max_pages=max_pages,
        max_ocr_pages=max_ocr_pages,
        ocr_enabled=ocr_enabled,
        doc_type=doc_type,
    )
    tables = extract_pdf_tables(path, max_pages=max_table_pages) if need_tables else []
    return {
        "pages_text": pages_text,
        "full_text": "\n".join(pages_text),
        "tables": tables,
    }

