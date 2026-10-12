from pathlib import Path
from uuid import uuid4
from datetime import datetime
import json

from config import PREPROCESSED_DIR, OCR_DIR, RESULT_DIR, DOCUMENT_TYPES, DOCUMENT_FIELDS
from src.ocr.preprocess import preprocess_image
from src.ocr.engine import run_ocr
from src.extraction.pdf_extractor import extract_pdf_document
from src.extraction.document_parser import parse_document
from src.extraction.label_parser import extract_label_data
from src.matching.fuzzy_matcher import cross_check
from src.matching.cross_check_engine import generate_cross_check_report
from src.validation.rules import validate_cross_checks, document_presence, evaluate_application_compliance
from src.extraction.entity_builder import consolidate_application


# Page limits for thick narrative documents to prevent reading 80+ pages when metadata is in the first few pages
DOC_PAGE_LIMITS = {
    "sistem_manajemen": 12,
    "program_perawatan": 18,
    "ppkr": 20,
}

# Digital documents that strictly do not use OCR (extracted purely via native digital PDF text/tables)
NO_OCR_DOCS = {
    "sistem_manajemen",
    "program_perawatan",
    "ppkr",
}


def _process_pdf(doc_type, path, context=None):
    need_tables = doc_type in {"formulir", "ppkr", "persetujuan_import", "uji_kesesuaian", "uji_fungsi"}
    max_pages = DOC_PAGE_LIMITS.get(doc_type)
    ocr_enabled = doc_type not in NO_OCR_DOCS
    max_ocr = 3 if doc_type in {"sib", "sip", "sprint", "tld", "paparan_radiasi", "uji_fungsi", "formulir"} else 1
    extracted = extract_pdf_document(
        path,
        need_tables=need_tables,
        max_pages=max_pages,
        max_table_pages=10 if doc_type == "ppkr" else 5,
        max_ocr_pages=max_ocr,
        ocr_enabled=ocr_enabled,
        doc_type=doc_type,
    )

    # Pipeline safeguard: If a document defaulted to 'formulir' but its content clearly matches
    # another specific BAPETEN certificate/report, auto-reclassify to avoid empty extraction.
    actual_doc_type = doc_type
    if doc_type == "formulir" and extracted.get("pages_text"):
        import re
        first_page_upper = extracted["pages_text"][0].upper()
        if not re.search(r"FORMULIR\s+PERMOHONAN|PERMOHONAN\s+IZIN|TENAGA\s+NUKLIR", first_page_upper):
            from src.extraction.classifier import CONTENT_PATTERNS
            for pat, dt in CONTENT_PATTERNS:
                if dt != "formulir" and re.search(pat, first_page_upper):
                    actual_doc_type = dt
                    break

    parsed = parse_document(actual_doc_type, extracted["pages_text"], extracted["tables"], context=context)
    parsed["document_type"] = actual_doc_type
    parsed["file_name"] = Path(path).name
    parsed["file_path"] = str(path)
    parsed["source_kind"] = "pdf"
    parsed["page_count"] = len(extracted["pages_text"])

    if actual_doc_type == "sprint":
        try:
            from src.extraction.signature_cropper import crop_and_save_sprint_signature
            sig_page = (parsed.get("fields", {}).get("pengesahan", {}).get("page") or 1) - 1
            crop_res = crop_and_save_sprint_signature(path, page_idx=sig_page)
            if crop_res:
                parsed["signature_crop_path"] = crop_res["crop_path"]
                parsed["signature_crop_base64"] = crop_res["crop_base64"]
                if "pengesahan" in parsed.get("fields", {}):
                    parsed["fields"]["pengesahan"]["crop_image"] = crop_res["crop_path"]
                    parsed["fields"]["pengesahan"]["crop_base64"] = crop_res["crop_base64"]
        except Exception:
            pass

    return parsed


def _convert_label_to_image(path: Path):
    """If path is a PDF, renders its pages (max 3) vertically into a temporary image. Returns (image_path, is_temp)."""
    path = Path(path)
    if path.suffix.lower() == ".pdf":
        import pypdfium2 as pdfium
        import tempfile
        from PIL import Image
        
        doc = pdfium.PdfDocument(str(path))
        try:
            images = []
            for i in range(min(len(doc), 3)):
                page = doc[i]
                images.append(page.render(scale=1.5).to_pil())
            
            if not images:
                return path, False
                
            if len(images) == 1:
                final_img = images[0]
            else:
                total_height = sum(img.height for img in images)
                max_width = max(img.width for img in images)
                final_img = Image.new('RGB', (max_width, total_height))
                y_offset = 0
                for img in images:
                    final_img.paste(img, (0, y_offset))
                    y_offset += img.height

            tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
            tmp_path = Path(tmp.name)
            tmp.close()
            final_img.save(str(tmp_path))
            return tmp_path, True
        finally:
            doc.close()
    return path, False


def _process_label(doc_type, path, run_id):
    path = Path(path)
    from src.ocr.engine import get_file_hash
    cache_key = get_file_hash(str(path))
    img_path, is_temp = _convert_label_to_image(path)
    try:
        original_lines = run_ocr(str(img_path), cache_key=cache_key)
        ocr_output = OCR_DIR / f"{run_id}_{doc_type}_{path.stem}.json"
        ocr_output.write_text(json.dumps(original_lines, ensure_ascii=False, indent=2), encoding="utf-8")

        original = extract_label_data(original_lines, doc_type)
        orig_fields = original.get("fields", {})

        # Check if original image OCR already cleanly extracted required fields.
        # If yes, we can skip the expensive preprocessing + secondary OCR pass!
        has_sufficient_fields = False
        if doc_type == "label_unit":
            b = orig_fields.get("unit_brand", {}).get("value")
            s = orig_fields.get("unit_serial_number", {}).get("value")
            t = orig_fields.get("unit_type", {}).get("value")
            has_sufficient_fields = bool(s and (b or t))
        elif doc_type in {"label_tabung", "label_tube"}:
            b = orig_fields.get("tube_brand", {}).get("value")
            s = orig_fields.get("tube_serial_number", {}).get("value")
            m = orig_fields.get("tube_unit_model", {}).get("value") or orig_fields.get("tube_insert_model", {}).get("value")
            has_sufficient_fields = bool(s and (b or m))

        if has_sufficient_fields:
            return {
                "document_type": doc_type,
                "file_name": path.name,
                "file_path": str(path),
                "source_kind": "image",
                "fields": orig_fields,
                "ocr": {
                    "original_lines": original_lines,
                    "preprocessed_lines": [],
                    "preprocessed_path": "",
                    "ocr_output": str(ocr_output),
                },
            }

        # Fallback to secondary OCR with image preprocessing if original was incomplete
        preprocessed_path = PREPROCESSED_DIR / f"{run_id}_{doc_type}_{path.stem}.png"
        preprocess_image(img_path, preprocessed_path)
        pre_lines = run_ocr(str(preprocessed_path), cache_key=cache_key + "_pre")
        preprocessed = extract_label_data(pre_lines, doc_type)

        # Prefer an original value when present; use preprocessed OCR only when original is missing.
        fields = {}
        all_keys = set(orig_fields) | set(preprocessed["fields"])
        for key in all_keys:
            left = orig_fields.get(key, {})
            right = preprocessed["fields"].get(key, {})
            if left.get("value") not in ("", None, "-", "—"):
                fields[key] = left
            elif right.get("value") not in ("", None, "-", "—"):
                fields[key] = {**right, "method": "ocr_preprocessed"}
            else:
                fields[key] = left or right or {"value": "-", "method": "not_found"}

        from src.extraction.document_parser import _finalize_document_fields
        fields = _finalize_document_fields(doc_type, fields)

        return {
            "document_type": doc_type,
            "file_name": path.name,
            "file_path": str(path),
            "source_kind": "image",
            "fields": fields,
            "ocr": {
                "original_lines": original_lines,
                "preprocessed_lines": pre_lines,
                "preprocessed_path": str(preprocessed_path),
                "ocr_output": str(ocr_output),
            },
        }
    finally:
        if is_temp and img_path.exists():
            try:
                img_path.unlink()
            except OSError:
                pass


def execute_run(document_inputs, on_progress=None):
    """Process a mapping {document_type: [paths]} and cross-check extracted fields."""
    run_id = uuid4().hex[:12]
    extractions = {key: [] for key in DOCUMENT_TYPES}

    # Calculate total files
    total_files = sum(len(paths) for paths in document_inputs.values() if paths)
    processed_count = 0
    running_context = {}

    DOC_PRIORITY = {
        "formulir": 0,
        "ppkr": 1,
        "label_unit": 2,
        "label_tabung": 3,
        "uji_kesesuaian": 4,
        "paparan_radiasi": 5,
        "uji_fungsi": 6,
        "persetujuan_import": 7,
    }

    sorted_doc_types = sorted(
        document_inputs.keys(),
        key=lambda dt: DOC_PRIORITY.get(dt, 50)
    )

    for doc_type in sorted_doc_types:
        paths = document_inputs[doc_type]
        if doc_type not in DOCUMENT_TYPES:
            continue
        for path in paths or []:
            processed_count += 1
            if on_progress:
                on_progress(doc_type, Path(path).name, processed_count, total_files)

            if DOCUMENT_TYPES[doc_type]["kind"] == "image":
                result = _process_label(doc_type, path, run_id)
            else:
                result = _process_pdf(doc_type, path, context=running_context)
            target_bucket = result.get("document_type") or doc_type
            if target_bucket not in extractions:
                extractions[target_bucket] = []
            extractions[target_bucket].append(result)

            # Update running context with extracted hospital/serial info
            f_fields = result.get("fields", {})
            for key in ["hospital_name", "hospital_address", "unit_serial_number", "unit_brand", "unit_type"]:
                val = f_fields.get(key, {}).get("value")
                if val and val not in ("-", "—") and key not in running_context:
                    running_context[key] = val

    checks = cross_check(extractions)
    validate_cross_checks(checks)
    application = consolidate_application(extractions)
    report = generate_cross_check_report(application, extractions, run_id)
    uploaded_keys = [k for k, p in document_inputs.items() if p]
    compliance = evaluate_application_compliance(application, uploaded_keys)

    result = {
        "run_id": run_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "application": application.model_dump(mode="json"),
        "cross_check_report": report.model_dump(mode="json"),
        "compliance": compliance.model_dump(mode="json"),
        "documents": {
            doc_type: [Path(p).name for p in paths]
            for doc_type, paths in document_inputs.items()
            if paths
        },
        "presence": document_presence(extractions, DOCUMENT_TYPES),
        "extractions": extractions,
        "cross_checks": checks,
        "summary": report.summary.model_dump(mode="json"),
        "schema": {
            "document_count": len(DOCUMENT_TYPES),
            "field_scope": DOCUMENT_FIELDS,
        },
    }

    output_path = RESULT_DIR / f"{run_id}.json"
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    result["artifacts"] = {"result_json": str(output_path)}
    return result
