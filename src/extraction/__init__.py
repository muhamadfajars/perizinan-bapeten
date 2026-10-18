"""Document extraction, parsing, classification, and entity consolidation."""

from src.extraction.classifier import classify_document
from src.extraction.document_parser import parse_document, extract_ppkr_data
from src.extraction.entity_builder import consolidate_application
from src.extraction.form_parser import extract_form_data, split_project_address
from src.extraction.label_parser import extract_label_data
from src.extraction.pdf_extractor import extract_pdf_document
from src.extraction.llm_extractor import extract_with_llm, merge_with_llm_fallback, is_ollama_available

__all__ = [
    "classify_document",
    "parse_document",
    "extract_ppkr_data",
    "consolidate_application",
    "extract_form_data",
    "split_project_address",
    "extract_label_data",
    "extract_pdf_document",
    "extract_with_llm",
    "merge_with_llm_fallback",
    "is_ollama_available",
]

