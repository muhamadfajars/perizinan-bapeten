"""Matching and normalization module for BAPETEN document cross-check."""

from .normalizer import (
    normalize,
    normalize_serial,
    normalize_date,
    normalize_person_name,
    normalize_address,
    normalize_brand,
    normalize_facility_name,
)
from .fuzzy_matcher import cross_check, compare_values, build_status_summary
from .cross_check_engine import (
    compare_two_values,
    evaluate_field_sources,
    cross_check_facility,
    cross_check_personnel,
    cross_check_ppr,
    cross_check_equipment,
    generate_cross_check_report,
)

__all__ = [
    "normalize",
    "normalize_serial",
    "normalize_date",
    "normalize_person_name",
    "normalize_address",
    "normalize_brand",
    "normalize_facility_name",
    "cross_check",
    "compare_values",
    "build_status_summary",
    "compare_two_values",
    "evaluate_field_sources",
    "cross_check_facility",
    "cross_check_personnel",
    "cross_check_ppr",
    "cross_check_equipment",
    "generate_cross_check_report",
]
