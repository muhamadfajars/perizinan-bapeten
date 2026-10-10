"""Parser for BAPETEN label images (Unit Label and Tube Label).

Extracts brand, model/type, and serial number from OCR lines with bounding boxes,
confidence ratings, and converts into domain entities.
"""

import re
from typing import Any, Dict, List, Optional, Tuple

from src.matching.normalizer import normalize
from src.schema.evidence import ExtractedField
from src.schema.entities import XRayEquipmentEntity, XRayTubeEntity


def sort_by_y(lines: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(lines or [], key=lambda l: (l.get("y", 0), l.get("x", 0)))


def text_lines(lines: List[Dict[str, Any]]) -> List[str]:
    return [str(x.get("text", "")).strip() for x in sort_by_y(lines) if str(x.get("text", "")).strip()]


def _extract_bbox(line: Optional[Dict[str, Any]]) -> Optional[List[float]]:
    if not line:
        return None
    if "bbox" in line and isinstance(line["bbox"], list):
        return line["bbox"]
    x = float(line.get("x", 0))
    y = float(line.get("y", 0))
    w = float(line.get("w", 0))
    h = float(line.get("h", 0))
    if w > 0 and h > 0:
        return [x, y, x + w, y + h]
    return None


DISALLOWED_LABEL_VALUES = {
    "NUMBER", "NO", "NO.", "NUM", "NAME", "CODE", "KODE", "TYPE", "MODEL", "SER", "SERIAL", "DESCRIPTION", "DESC"
}


def _find_adjacent_box_value(
    label_line: Dict[str, Any],
    all_lines: List[Dict[str, Any]],
    is_serial: bool = False,
) -> Tuple[str, Optional[Dict[str, Any]]]:
    """Finds the value in an adjacent bounding box (horizontally to the right or vertically below)."""
    lx = float(label_line.get("x", 0))
    ly = float(label_line.get("y", 0))

    # Check horizontally to the right: x > lx + 15, abs(y - ly) < 70
    candidates_right = [
        l for l in all_lines
        if float(l.get("x", 0)) > lx + 15 and abs(float(l.get("y", 0)) - ly) < 70
    ]
    # Check vertically below: 0 < y - ly < 80, abs(x - lx) < 150
    candidates_below = [
        l for l in all_lines
        if 0 < float(l.get("y", 0)) - ly < 80 and abs(float(l.get("x", 0)) - lx) < 150
    ]

    combined = candidates_right + candidates_below
    valid_candidates = []
    for c in combined:
        txt = str(c.get("text", "")).strip()
        if not txt or txt.upper() in DISALLOWED_LABEL_VALUES:
            continue
        # Avoid label headers
        if re.match(r"^(?:MODEL|TYPE|S/N|SN|DESC|CE|ETL|MANUFACTURED|DATE|VOLT|KV|MA)\b", txt, re.IGNORECASE):
            continue
        if is_serial and not re.match(r"^[A-Za-z0-9\-]+$", txt):
            continue
        dist = (float(c.get("x", 0)) - lx) ** 2 + (float(c.get("y", 0)) - ly) ** 2
        valid_candidates.append((dist, txt, c))

    if valid_candidates:
        valid_candidates.sort(key=lambda item: item[0])
        return valid_candidates[0][1], valid_candidates[0][2]

    return "", None


def _find_line_value(lines: List[Dict[str, Any]], patterns: List[str]) -> Tuple[str, Optional[Dict[str, Any]]]:
    sorted_lines = sort_by_y(lines)
    for pattern in patterns:
        for line in sorted_lines:
            text = str(line.get("text", ""))
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                # If there's a capture group, take it; else whole match
                value = m.group(1).strip(" :;-\t") if m.groups() else m.group(0).strip(" :;-\t")
                if value and value.upper() not in DISALLOWED_LABEL_VALUES:
                    return value, line
                # If matched header without value or captured generic word like NUMBER, check adjacent box
                adj_val, adj_line = _find_adjacent_box_value(line, lines)
                if adj_val and adj_val.upper() not in DISALLOWED_LABEL_VALUES:
                    return adj_val, adj_line
    return "", None


def _first_conf(lines: List[Dict[str, Any]], value: str) -> float:
    norm_value = normalize(value)
    if not norm_value:
        return 0.90
    scores = []
    for line in lines:
        if norm_value and norm_value in normalize(line.get("text", "")):
            try:
                scores.append(float(line.get("conf", 0)))
            except (ValueError, TypeError):
                pass
    return min(scores) if scores else 0.90


def extract_brand_dynamically(lines: List[Dict[str, Any]]) -> Tuple[str, Optional[Dict[str, Any]]]:
    """Dynamically extracts manufacturer/brand from OCR lines without restricting to a fixed list."""
    # 1. Primary: Explicit manufacturer/brand label
    brand, brand_line = _find_line_value(
        lines,
        [
            r"(?:MANUFACTURER|MFR|MADE\s+BY|FABRIQUE\s+PAR|HERSTELLER|PRODUCED\s+BY|BRAND|MERK|PABRIKAN|DIPRODUKSI\s+OLEH)\s*[:\-]?\s*(.+)",
        ],
    )
    if brand:
        return brand, brand_line

    # 2. Known medical radiological equipment brands
    sorted_lines = sort_by_y(lines)
    common_medical_brands = [
        "SHIMADZU", "SIEMENS", "GENERAL ELECTRIC", "GE", "PHILIPS", "TOSHIBA",
        "CANON", "CANDN", "HITACHI", "CARESTREAM", "FUJIFILM", "FUJI", "HOLOGIC",
        "VATECH", "ALLENGERS", "SEDICAL", "VARIAN", "DUNLEE", "IAE", "ITALRAY", "VILLA"
    ]
    for brand_name in common_medical_brands:
        for line in sorted_lines:
            text = str(line.get("text", "")).strip()
            if re.search(rf"\b{re.escape(brand_name)}\b", text, re.IGNORECASE):
                return text, line

    # 3. Company indicator in lines (e.g., Corp, Co Ltd, GmbH, Inc, Medical Systems, Electron Tubes)
    for line in sorted_lines:
        text = str(line.get("text", "")).strip()
        if not text or len(text) < 3:
            continue
        if text.upper() in {"MEDICAL", "EQUIPMENT", "MEDICAL EQUIPMENT", "MEDICAL DEVICE"}:
            continue
        if re.search(r"^(?:MODEL|TYPE|TIPE|SER|S/N|SN|VOLT|KV|MA|HZ|DATE|TANGGAL|REF|LOT|CAT|CAUTION|WARNING|ATTENTION)\b", text, re.IGNORECASE):
            continue
        if re.search(r"\b(?:CORP(?:ORATION)?|CO\.?,?\s*LTD|INC\.?|GMBH|AG|HEALTHCARE|MEDICAL(?:\s+SYSTEMS)?|ELECTRON\s+TUBES)\b", text, re.IGNORECASE):
            return text, line

    # 4. Fallback: First line if clean text with Latin characters
    for line in sorted_lines[:5]:
        first_text = str(line.get("text", "")).strip()
        if (
            len(first_text) >= 3
            and re.search(r"[A-Za-z]{3,}", first_text)
            and not re.search(r"^(?:MODEL|TYPE|SER|S/N|SN|KV|MA|VOLT|DATE|CE\b|WARNING)\b", first_text, re.IGNORECASE)
        ):
            return first_text, line

    return "", None


def parse_label_unit(lines: List[Dict[str, Any]]) -> Dict[str, Any]:
    brand, brand_line = extract_brand_dynamically(lines)

    # 1. Serial Number: prioritize dedicated S/N or SN label with adjacent box support
    serial, serial_line = "", None
    for line in sort_by_y(lines):
        text = str(line.get("text", "")).strip()
        m_s = re.search(r"^(?:S\s*/\s*N|SN|SER(?:IAL)?(?:\s*(?:NO|NUMBER))?\.?)\s*[:\-]?\s*(.*)$", text, re.IGNORECASE)
        if m_s:
            val = m_s.group(1).strip(" :;-\t")
            if val and val.upper() not in DISALLOWED_LABEL_VALUES and re.match(r"^[A-Za-z0-9\-]+$", val):
                serial, serial_line = val, line
                break
            adj_val, adj_line = _find_adjacent_box_value(line, lines, is_serial=True)
            if adj_val and adj_val.upper() not in DISALLOWED_LABEL_VALUES and re.match(r"^[A-Za-z0-9\-]+$", adj_val):
                serial, serial_line = adj_val, adj_line
                break

    if not serial:
        serial, serial_line = _find_line_value(
            lines,
            [
                r"(?:S\s*/\s*N|SER(?:IAL)?(?:\s*(?:NO|NUMBER))?\.?)\s*[:\-]?\s*([A-Za-z0-9\-]+)",
                r"\bSN\s*[:\-]?\s*([A-Za-z0-9\-]+)",
            ],
        )

    # 2. Unit Model / Type: check commercial description (DESC) first, then MODEL/TYPE
    unit_type, type_line = "", None
    for line in sort_by_y(lines):
        text = str(line.get("text", "")).strip()
        m_desc = re.search(r"^(?:DESC(?:RIPTION)?)\s*[:\-]?\s*(.*)$", text, re.IGNORECASE)
        if m_desc:
            val = m_desc.group(1).strip(" :;-\t")
            if val and val.upper() not in DISALLOWED_LABEL_VALUES:
                unit_type, type_line = val, line
                break
            adj_val, adj_line = _find_adjacent_box_value(line, lines)
            if adj_val and adj_val.upper() not in DISALLOWED_LABEL_VALUES:
                unit_type, type_line = adj_val, adj_line
                break

    if not unit_type:
        unit_type, type_line = _find_line_value(
            lines,
            [
                r"(?:MODEL|MODÈLE|TYPE|TIPE)(?:\s*(?:NO\.?|NUMBER|NAME))?\s*[:\-]?\s*(.+)",
                r"(?:REF(?:ERENCE)?|CAT(?:ALOG)?)\s*[:\-]?\s*(.+)",
            ],
        )

    # Clean trailing electrical power specification (e.g. 'OPTIMA XR200AMX 30KW' -> 'OPTIMA XR200AMX')
    if unit_type:
        unit_type = re.sub(r"\s+\d+\s*KW\b", "", unit_type, flags=re.IGNORECASE).strip()

    return {
        "unit_brand": {
            "value": brand,
            "method": "ocr",
            "raw_text": brand_line.get("text") if brand_line else "",
            "bbox": _extract_bbox(brand_line),
        },
        "unit_serial_number": {
            "value": serial,
            "method": "ocr",
            "raw_text": serial_line.get("text") if serial_line else "",
            "bbox": _extract_bbox(serial_line),
        },
        "unit_type": {
            "value": unit_type,
            "method": "ocr",
            "raw_text": type_line.get("text") if type_line else "",
            "bbox": _extract_bbox(type_line),
        },
    }


def parse_label_tube(lines: List[Dict[str, Any]]) -> Dict[str, Any]:
    pairs = []
    for line in sort_by_y(lines):
        text = str(line.get("text", ""))
        m_model = re.search(r"(?:MODEL|TYPE|TIPE|HOUSING\s+MODEL|INSERT\s+MODEL)\s*[:\-]?\s*(.+)", text, re.IGNORECASE)
        if m_model:
            pairs.append(("model", m_model.group(1).strip(), line))
        m_serial = re.search(r"(?:SER\.?\s*(?:NO|NUMBER)?\.?|S\s*/\s*N)\s*[:\-]?\s*([A-Za-z0-9\-]+)", text, re.IGNORECASE)
        if m_serial:
            pairs.append(("serial", m_serial.group(1).strip(), line))

    models = [p for p in pairs if p[0] == "model"]
    serials = [p for p in pairs if p[0] == "serial"]

    brand, brand_line = extract_brand_dynamically(lines)

    m1_val, m1_line = (models[0][1], models[0][2]) if models else ("", None)
    m2_val, m2_line = (models[1][1], models[1][2]) if len(models) > 1 else ("", None)
    s_val, s_line = (serials[-1][1], serials[-1][2]) if serials else ("", None)

    return {
        "tube_unit_model": {
            "value": m1_val,
            "method": "ocr",
            "raw_text": m1_line.get("text") if m1_line else "",
            "bbox": _extract_bbox(m1_line),
        },
        "tube_insert_model": {
            "value": m2_val,
            "method": "ocr",
            "raw_text": m2_line.get("text") if m2_line else "",
            "bbox": _extract_bbox(m2_line),
        },
        "tube_serial_number": {
            "value": s_val,
            "method": "ocr",
            "raw_text": s_line.get("text") if s_line else "",
            "bbox": _extract_bbox(s_line),
        },
        "tube_brand": {
            "value": brand,
            "method": "ocr",
            "raw_text": brand_line.get("text") if brand_line else "",
            "bbox": _extract_bbox(brand_line),
        },
    }


def extract_label_data(lines: List[Dict[str, Any]], doc_type: str) -> Dict[str, Any]:
    parser = parse_label_unit if doc_type == "label_unit" else parse_label_tube
    values = parser(lines)
    for key, item in values.items():
        value = item.get("value", "")
        conf = _first_conf(lines, value) if value else 0.0
        item["confidence"] = conf
    return {"document_type": doc_type, "fields": values}


def build_label_unit_entity(
    lines: List[Dict[str, Any]],
    file_name: str,
    entity_id: str = "unit_label_1",
    page: int = 1,
) -> XRayEquipmentEntity:
    """Builds an XRayEquipmentEntity from unit label OCR results."""
    parsed = parse_label_unit(lines)
    brand_info = parsed["unit_brand"]
    type_info = parsed["unit_type"]
    serial_info = parsed["unit_serial_number"]

    return XRayEquipmentEntity(
        id=entity_id,
        unit_brand=ExtractedField[str].from_value(
            value=brand_info["value"],
            document_type="label_unit",
            file_name=file_name,
            page=page,
            raw_text=brand_info.get("raw_text"),
            confidence=_first_conf(lines, brand_info["value"]),
            extraction_method="ocr",
        ),
        unit_type=ExtractedField[str].from_value(
            value=type_info["value"],
            document_type="label_unit",
            file_name=file_name,
            page=page,
            raw_text=type_info.get("raw_text"),
            confidence=_first_conf(lines, type_info["value"]),
            extraction_method="ocr",
        ),
        unit_serial_number=ExtractedField[str].from_value(
            value=serial_info["value"],
            document_type="label_unit",
            file_name=file_name,
            page=page,
            raw_text=serial_info.get("raw_text"),
            confidence=_first_conf(lines, serial_info["value"]),
            extraction_method="ocr",
        ),
    )


def build_label_tube_entity(
    lines: List[Dict[str, Any]],
    file_name: str,
    entity_id: str = "tube_label_1",
    page: int = 1,
) -> XRayTubeEntity:
    """Builds an XRayTubeEntity from tube label OCR results."""
    parsed = parse_label_tube(lines)
    brand_info = parsed["tube_brand"]
    unit_model = parsed["tube_unit_model"]
    insert_model = parsed["tube_insert_model"]
    serial_info = parsed["tube_serial_number"]

    model_val = unit_model["value"] or insert_model["value"]
    model_raw = unit_model.get("raw_text") or insert_model.get("raw_text")

    return XRayTubeEntity(
        id=entity_id,
        tube_brand=ExtractedField[str].from_value(
            value=brand_info["value"],
            document_type="label_tabung",
            file_name=file_name,
            page=page,
            raw_text=brand_info.get("raw_text"),
            confidence=_first_conf(lines, brand_info["value"]),
            extraction_method="ocr",
        ),
        tube_type=ExtractedField[str].from_value(
            value=model_val,
            document_type="label_tabung",
            file_name=file_name,
            page=page,
            raw_text=model_raw,
            confidence=_first_conf(lines, model_val),
            extraction_method="ocr",
        ),
        tube_model=ExtractedField[str].from_value(
            value=model_val,
            document_type="label_tabung",
            file_name=file_name,
            page=page,
            raw_text=model_raw,
            confidence=_first_conf(lines, model_val),
            extraction_method="ocr",
        ),
        tube_serial_number=ExtractedField[str].from_value(
            value=serial_info["value"],
            document_type="label_tabung",
            file_name=file_name,
            page=page,
            raw_text=serial_info.get("raw_text"),
            confidence=_first_conf(lines, serial_info["value"]),
            extraction_method="ocr",
        ),
    )
