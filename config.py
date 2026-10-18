from pathlib import Path

from src.schema.fields import DOCUMENT_TYPES, DOCUMENT_FIELDS, CROSS_CHECK_RULES, FIELD_DEFINITIONS

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
INPUT_DIR = DATA_DIR / "input"
OUTPUT_DIR = DATA_DIR / "output"

INPUT_ARCHIVE_DIR = INPUT_DIR / "documents"
LABEL_DIR = INPUT_DIR / "labels"
PREPROCESSED_DIR = OUTPUT_DIR / "preprocessed"
OCR_DIR = OUTPUT_DIR / "ocr"
RESULT_DIR = OUTPUT_DIR / "results"
CROPS_DIR = OUTPUT_DIR / "crops"
DB_PATH = OUTPUT_DIR / "bapeten_matching.sqlite3"

OCR_LANG = "en"
FAST_MODE = True
OCR_CONFIDENCE_REVIEW_THRESHOLD = 0.90

# Prototype-derived assumptions that remain configurable.
FORM_GENERATOR_TABLE_INDEX = -1
MATCH_THRESHOLD = 90
REVIEW_THRESHOLD = 60
BRAND_FUZZY_THRESHOLD = 80
ADDRESS_MATCH_THRESHOLD = 85.0

BRAND_ALIASES = {
    "GE": ["GENERAL ELECTRIC", "GE HEALTHCARE", "GE MEDICAL"],
    "CANON": ["CANON"],
    "UNITED IMAGING": ["UNITED IMAGING HEALTHCARE", "SHANGHAI UNITED IMAGING HEALTHCARE", "UIH"],
}
BRAND_FULL_NAMES = {
    "GE": ["General Electric Company"],
    "CANON": ["Canon Electron Tubes & Devices Co., Ltd."],
    "UNITED IMAGING": ["Shanghai United Imaging Healthcare Co., Ltd."],
}

# Extraction scope comes from the user's field-identification document.
MASTER_DOCUMENT_FIELDS = DOCUMENT_FIELDS
MASTER_CROSS_CHECK_RULES = CROSS_CHECK_RULES

# LLM Extraction configuration (Ollama local inference)
OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_MODEL = "qwen2.5:7b"
USE_LLM_EXTRACTION = True
LLM_TIMEOUT_SECONDS = 60.0
HIGH_VARIANCE_DOCS = {
    "uji_fungsi",
    "persetujuan_import",
    "spesifikasi_pesawat",
    "paparan_radiasi",
}

for path in [INPUT_ARCHIVE_DIR, LABEL_DIR, PREPROCESSED_DIR, OCR_DIR, RESULT_DIR, CROPS_DIR]:
    path.mkdir(parents=True, exist_ok=True)

