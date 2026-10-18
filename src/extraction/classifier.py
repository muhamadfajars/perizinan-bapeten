"""Automatic document type classifier based on filename patterns, PDF header inspection, and fast OCR."""

import io
import json
import re
from pathlib import Path
from typing import Optional, Tuple

from config import DOCUMENT_TYPES, OCR_DIR

# Keyword patterns for filename matching (ordered strictly by specificity)
FILENAME_PATTERNS = [
    # 1. High-priority compound patterns
    (r"\b(?:program[\s_]+perawatan|perawatan[\s_]+pesawat|maintenance[\s_]+program|pemeliharaan|jadwal[\s_]+perawatan)\b", "program_perawatan"),
    (r"\b(?:paparan|pengukuran[\s_]+radiasi|radiasi[\s_]+ruang|kebocoran[\s_]+tabung|kebocoran|survey[\s_]+radiasi|survey[\s_]+meter|survei|denah[\s_]+ruang|denah)\b", "paparan_radiasi"),
    (r"\b(?:uji[\s_]+fungsi|ujifungsi|functional[\s_]+test|caf\b|bauf\b|bast\b|customer[\s_]+acceptance|acceptance[\s_]+test|service[\s_]+report|medical[\s_]+system|berita[\s_]+acara[\s_]+uji|berita[\s_]+acara[\s_]+serah|commissioning|test[\s_]+and[\s_]+verification|installation[\s_]+and[\s_]+verification|installation[\s_]+record|verification[\s_]+record|installation[\s_]+report|system[\s_]+installation|xr[\s_]+system|installation)\b", "uji_fungsi"),
    (r"\b(?:uji[\s_]+kesesuaian|kesesuaian|lhu\b|lehu\b|compliance[\s_]+test|sertifikat[\s_]+kesesuaian|sertifikat[\s_]+uk\b|ktun[\s_]+(?:sertifikat[\s_]+)?uk\b|ktun[\s_]+uk\b|laporan[\s_]+kesesuaian|hasil[\s_]+uji[\s_]+kesesuaian)\b", "uji_kesesuaian"),
    (r"\b(?:sistem[\s_]+manajemen|manajemen[\s_]+fasilitas|quality[\s_]+management|dokumen[\s_]+manajemen)\b", "sistem_manajemen"),
    (r"\b(?:ppkr\b|proteksi[\s_]+keselamatan|program[\s_]+proteksi|keselamatan[\s_]+radiasi|radiation[\s_]+safety|radiation[\s_]+protection|proteksi[\s_]+radiasi)\b", "ppkr"),
    (r"\b(?:formulir|ktun|form[\s_]+permohonan|permohonan[\s_]+izin|surat[\s_]+permohonan|aplikasi[\s_]+izin)\b", "formulir"),
    (r"\b(?:sip\b|sikr\b|surat[\s_]+izin[\s_]+prakt?ik|surat[\s_]+izin[\s_]+kerja|izin[\s_]+prakt?ik|izin[\s_]+praktek|izin[\s_]+kerja|sip[\s_]+dokter|sip[\s_]+dr|sikr[\s_]+radiografer|sip[\s_]+radiografer)\b", "sip"),
    (r"\b(?:sprint\b|sprin\b|surat[\s_]+perintah|surat[\s_]+tugas|sk[\s_]+ppr|sk[\s_]+petugas|sk[\s_]+penunjukan|penunjukan[\s_]+ppr|penetapan[\s_]+ppr|penunjukan[\s_]+tugas)\b", "sprint"),
    (r"\b(?:sib\b|surat[\s_]+izin[\s_]+bekerja|izin[\s_]+bekerja|lisensi[\s_]+ppr|sertifikat[\s_]+ppr|kartu[\s_]+sib|sertifikat[\s_]+kompetensi[\s_]+(?:petugas[\s_]+proteksi|ppr)|sertifikat[\s_]+kompetensi)\b", "sib"),
    (r"\b(?:laporan[\s_]+dosis[\s_]+awal|dosis[\s_]+awal|lencana[\s_]+osl|oslindo|laporan[\s_]+dosis|osl\b|zero[\s_]+check|zerocheck|dosis[\s_]+perorangan)\b", "laporan_dosis_awal"),
    (r"\b(?:rencana[\s_]+teknis|gedung[\s_]+penahan|penahan[\s_]+radiasi|ruang[\s_]+penahan|dinding[\s_]+penahan|shielding)\b", "gedung_penahan_radiasi"),

    (r"\b(?:tld\b|dosimeter|nuklindo|dosis[\s_]+radiasi|kartu[\s_]+dosis|evaluasi[\s_]+dosis)\b", "tld"),
    (r"\b(?:persetujuan[\s_]+impor|persetujuan[\s_]+import|izin[\s_]+impor|izin[\s_]+import|surat[\s_]+impor|surat[\s_]+import|impor\b|import\b|\bpi[\s_]*(?:alat|sinar|xray|bapeten)\b)\b", "persetujuan_import"),
    (r"\b(?:spesifikasi|spek\b|specification|manual[\s_]+book|datasheet|data[\s_]+sheet|brosur|brochure|technical[\s_]+spec|user[\s_]+manual)\b", "spesifikasi_pesawat"),
    (r"\b(?:label[\s_]+tabung|foto[\s_]+tabung|plat[\s_]+tabung|tube[\s_]+label|tube[\s_]+plate|tube[\s_]+housing|housing[\s_]+tabung|insert[\s_]+tube|insert[\s_]+tabung|tabung[\s_]+sinar|xray[\s_]+tube|x_ray[\s_]+tube)\b", "label_tabung"),
    (r"\b(?:label[\s_]+(?:unit|pesawat)[\s_]+(?:dan|&|and)?[\s_]*(?:tabung|tube)|foto[\s_]+label[\s_]+(?:unit[\s_]+dan[\s_]+tabung|gabungan)|plat[\s_]+(?:unit[\s_]+dan[\s_]+tabung|gabungan))\b", "label_unit"),
    (r"\b(?:label[\s_]+unit|foto[\s_]+unit|plat[\s_]+unit|unit[\s_]+label|unit[\s_]+plate|foto[\s_]+keseluruhan|generator|xray[\s_]+unit|pesawat[\s_]+sinar|unit[\s_]+pesawat|control[\s_]+panel)\b", "label_unit"),
    (r"\b(?:tabung|tube)\b", "label_tabung"),
    (r"\b(?:unit|pesawat)\b", "label_unit"),
    (r"\b(?:perawatan|pemeliharaan|maintenance)\b", "program_perawatan"),
    (r"\b(?:manajemen)\b", "sistem_manajemen"),
    (r"\b(?:permohonan)\b", "formulir"),
]

# Content keyword patterns from the text of a PDF
CONTENT_PATTERNS = [
    (r"LAPORAN\s+DOSIS\s+AWAL|LENCANA\s+OSL|OSLINDO|MAQASS\s+TECHRAD|ZERO\s+CHECK|DOSIS\s+PERORANGAN\s+DENGAN\s+LENCANA\s+TLD", "laporan_dosis_awal"),
    (r"RENCANA\s+TEKNIS\s+FASILITAS|GEDUNG\s+PENAHAN\s+RADIASI|PENAHAN\s+RADIASI\s+RUANG\s+RADIOLOGI|DINDING\s+PENAHAN\s+RADIASI", "gedung_penahan_radiasi"),
    (r"SISTEM\s+MANAJEMEN\s+FASILITAS|SISTEM\s+MANAJEMEN\s+KESELAMATAN|SISTEM\s+MANAJEMEN\b", "sistem_manajemen"),
    (r"PROGRAM\s+PERAWATAN\s+PESAWAT\s+SINAR|PROGRAM\s+PERAWATAN\b", "program_perawatan"),
    (r"PROGRAM\s+PROTEKSI\s+DAN\s+KESELAMATAN\s+RADIASI|\bPPKR\b", "ppkr"),
    (r"PENGUKURAN\s+PAPARAN|PAPARAN\s+RADIASI|KEBOCORAN\s+TABUNG|DENAH\s+RUANG|SURVEY\s+METER", "paparan_radiasi"),
    (r"UJI\s+KESESUAIAN|LAPORAN\s+EVALUASI\s+HASIL\s+UJI|LEHU\b|LAPORAN\s+HASIL\s+UJI\s+KESESUAIAN|SERTIFIKAT\s+(?:HASIL\s+)?UJI\s+KESESUAIAN|LEMBAR\s+HASIL\s+UJI\s+KESESUAIAN", "uji_kesesuaian"),
    (r"FORMULIR\s+PERMOHONAN|PERMOHONAN\s+IZIN\s+PEMANFAATAN", "formulir"),
    (r"NUKLINDOLAB|KOPERASI\s+JASA\s+KESELAMATAN|TLD\s+BETA|DOSIS|DOSIMETER", "tld"),
    (r"SURAT\s+IZIN\s+PRAKT?IK|\bSIP\b|TEMPAT\s+PRAKT?IK|SURAT\s+IZIN\s+KERJA\s+RADIOGRAFER|\bSIKR\b|SURAT\s+IZIN\s+KERJA", "sip"),
    (r"SURAT\s+PERINTAH|\bSPRINT\b|\bSPRIN\b|MEMERINTAHKAN\s*:|SURAT\s+PENUNJUKAN\s+TUGAS|SURAT\s+TUGAS|MENUGASKAN\s+KEPADA", "sprint"),
    (r"SURAT\s+IZIN\s+BEKERJA|\bSIB\b|PETUGAS\s+PROTEKSI\s+RADIASI\s+BIDANG|WORKING\s+PERMIT\s+OF\s+OFFICER|SERTIFIKAT\s+KOMPETENSI\s+PETUGAS\s+PROTEKSI\s+RADIASI|RADIATION\s+PROTECTION\s+OFFICER\s+COMPETENCY|UJIAN\s+SERTIFIKASI\s+KOMPETENSI", "sib"),
    (r"HASIL\s+UJI\s+FUNGSI|LEMBAR\s+HASIL\s+UJI\s+FUNGSI|BERITA\s+ACARA\s+UJI\s+FUNGSI|BERITA\s+ACARA\s+SERAH\s+TERIMA|SERVICE\s+REPORT|ACCEPTANCE\s+TEST|CUSTOMER\s+ACCEPTANCE|FUNCTIONAL\s+TEST|COMMISSIONING|TEST\s+AND\s+VERIFICATION|INSTALLATION\s+AND\s+VERIFICATION|INSTALLATION\s+RECORD|VERIFICATION\s+RECORD|PTC\s+WINDCHILL|SYSTEM\s+INSTALLATION|INSTALLATION\s+PROCEDURE|INSTALLATION\s+CONCLUSION|CUSTOMER\s+SERVICE\s+ENGINEER", "uji_fungsi"),
    (r"PERSETUJUAN\s+IMPOR|PERSETUJUAN\s+IMPORT|SURAT\s+PERSETUJUAN\s+IMPOR", "persetujuan_import"),
    (r"SPESIFIKASI\s+TEKNIS|SPESIFIKASI\s+PESAWAT|TECHNICAL\s+SPECIFICATION|SPECIFICATIONS?|RADIOGRAPHIC\s+SYSTEM|OPERATOR[\'S ]+MANUAL|USER[\'S ]+MANUAL|BROCHURE", "spesifikasi_pesawat"),
    (r"X-RAY\s+TUBE|TUBE\s+HOUSING|TUBE\s+INSERT|ROTANODE|NAMEPLATE|RATING\s+PLATE|LABEL\s+PESAWAT|LABEL\s+TABUNG|LABEL\s+UNIT|管芯型号|产品型号", "label_unit"),
]


def classify_by_filename(filename: str) -> Optional[str]:
    """Matches filename against recognized document type keywords."""
    name_clean = re.sub(r"[_\-\s\.]+", " ", filename).lower()
    for pattern, doc_type in FILENAME_PATTERNS:
        if re.search(pattern, name_clean, re.IGNORECASE):
            return doc_type
    return None


def _fast_ocr_header(file_bytes: bytes) -> str:
    """Renders the top 35% banner of page 1 and runs quick OCR to read the document title."""
    import tempfile
    import pypdfium2 as pdfium
    from src.ocr.engine import get_file_hash, run_ocr

    cache_key = get_file_hash(file_bytes[:4096]) + "_hdr_class"
    disk_file = OCR_DIR / f"{cache_key}.json"
    if disk_file.exists():
        try:
            with open(disk_file, "r", encoding="utf-8") as f:
                lines = json.load(f)
                return " ".join(l.get("text", "") for l in lines)
        except Exception:
            pass

    try:
        doc = pdfium.PdfDocument(io.BytesIO(file_bytes))
        if len(doc) == 0:
            return ""
        page = doc[0]
        # Low scale 1.0 is fast and sufficient for large header titles
        img = page.render(scale=1.0).to_pil()
        w, h = img.size
        crop_img = img.crop((0, 0, w, int(h * 0.35)))
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            crop_img.save(tmp_path)
            lines = run_ocr(tmp_path, cache_key=cache_key)
            return " ".join(l.get("text", "") for l in lines)
        finally:
            if Path(tmp_path).exists():
                try:
                    Path(tmp_path).unlink()
                except OSError:
                    pass
    except Exception:
        return ""


def classify_image_by_ocr(file_bytes: bytes) -> Optional[str]:
    """Runs fast OCR on downscaled plate photo to differentiate label_tabung vs label_unit."""
    import tempfile
    from PIL import Image
    from src.ocr.engine import get_file_hash, run_ocr

    cache_key = get_file_hash(file_bytes[:4096]) + "_img_class"
    disk_file = OCR_DIR / f"{cache_key}.json"
    lines = []
    if disk_file.exists():
        try:
            with open(disk_file, "r", encoding="utf-8") as f:
                lines = json.load(f)
        except Exception:
            pass

    if not lines:
        try:
            img = Image.open(io.BytesIO(file_bytes))
            img.thumbnail((600, 600))
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp_path = tmp.name
            try:
                img.save(tmp_path)
                lines = run_ocr(tmp_path, cache_key=cache_key)
            finally:
                if Path(tmp_path).exists():
                    try:
                        Path(tmp_path).unlink()
                    except OSError:
                        pass
        except Exception:
            return None

    text = " ".join(l.get("text", "") for l in lines).upper()
    if re.search(r"\b(TUBE|HOUSING|INSERT|FOCAL|ANODE|TARGET|INHERENT|FILTRATION|TABUNG)\b", text):
        return "label_tabung"
    if re.search(r"\b(GENERATOR|X-?RAY\s+UNIT|RADIOGRAPHY|CONTROL\s+PANEL|SYSTEM|MEJA|STAND|PESAWAT)\b", text):
        return "label_unit"
    return None


def classify_by_content(file_bytes: bytes) -> Tuple[Optional[str], str]:
    """Inspects text from the first 5 pages of a PDF to detect document type.
    
    If digital text is sparse (<30 characters, e.g. scanned PDF), renders page 1 header and runs quick OCR.
    Returns (doc_type, reason)
    """
    native_text = ""
    try:
        import pypdfium2 as pdfium
        doc = pdfium.PdfDocument(io.BytesIO(file_bytes))
        try:
            for i in range(min(5, len(doc))):
                page = doc[i]
                textpage = page.get_textpage()
                native_text += (textpage.get_text_bounded() or "") + "\n"
                
            text_upper = native_text.upper()
            if len(re.findall(r"[A-Za-z]", text_upper)) >= 25:
                for pattern, doc_type in CONTENT_PATTERNS:
                    if re.search(pattern, text_upper, re.IGNORECASE):
                        return doc_type, "Teks Digital Dokumen"
        finally:
            doc.close()
    except Exception:
        pass

    # Fallback to fast header OCR for scanned PDF documents
    header_text = _fast_ocr_header(file_bytes)
    if header_text:
        header_upper = header_text.upper()
        for pattern, doc_type in CONTENT_PATTERNS:
            if re.search(pattern, header_upper, re.IGNORECASE):
                return doc_type, "OCR Kop / Judul Dokumen"

    return None, "Default"


def classify_document(filename: str, file_bytes: Optional[bytes] = None) -> Tuple[str, str]:
    """Identifies the BAPETEN document type for a given uploaded file.
    
    Returns (doc_type, detection_reason)
    """
    ext = Path(filename).suffix.lower()
    is_image = ext in {".jpg", ".jpeg", ".png", ".webp", ".bmp"}

    # 1. First attempt: match by filename
    by_name = classify_by_filename(filename)
    if by_name:
        return by_name, "Nama Berkas"

    # 2. For image files without explicit name match
    if is_image:
        if file_bytes:
            img_type = classify_image_by_ocr(file_bytes)
            if img_type:
                reason = "OCR Plat Tabung" if img_type == "label_tabung" else "OCR Plat Unit"
                return img_type, reason
        if re.search(r"tabung|tube|insert|housing", filename, re.I):
            return "label_tabung", "Format Gambar (Tabung)"
        return "label_unit", "Format Gambar (Unit Sinar-X)"

    # 3. For PDF files: inspect first page text content (digital or scanned OCR)
    if file_bytes:
        by_content, reason = classify_by_content(file_bytes)
        if by_content:
            return by_content, reason

    # 4. Fallback if unrecognized
    return "formulir", "Default"
