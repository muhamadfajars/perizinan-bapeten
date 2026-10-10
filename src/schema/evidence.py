"""Evidence and source tracking models for BAPETEN Document Matching System."""

from typing import Any, Generic, List, Optional, TypeVar
from pydantic import BaseModel, Field, ConfigDict

T = TypeVar("T")


class EvidenceSource(BaseModel):
    """Tracks the exact origin of an extracted field value."""
    document_type: str = Field(..., description="Document type key, e.g., formulir, ppkr, label_unit, sip, sib")
    file_name: str = Field(..., description="Original file name")
    page: Optional[int] = Field(default=None, description="1-indexed page number in PDF, or 1 for image")
    raw_text: Optional[str] = Field(default=None, description="Raw text snippet containing the value")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Confidence score (0.0 to 1.0)")
    bbox: Optional[List[float]] = Field(default=None, description="Optional bounding box [x1, y1, x2, y2]")
    extraction_method: str = Field(default="unknown", description="Method used: table_cell, regex, ocr, manual")

    model_config = ConfigDict(populate_by_name=True)


class ExtractedField(BaseModel, Generic[T]):
    """Wraps an extracted value with its source evidence and metadata."""
    value: Optional[T] = Field(default=None, description="Cleaned/parsed value")
    raw_value: Optional[str] = Field(default=None, description="Raw string value before normalization")
    normalized_value: Optional[str] = Field(default=None, description="Canonical normalized string for matching")
    evidence: Optional[EvidenceSource] = Field(default=None, description="Evidence source where value was found")

    @property
    def is_present(self) -> bool:
        if self.value is None:
            return False
        if isinstance(self.value, str) and not self.value.strip():
            return False
        return True

    @classmethod
    def from_value(
        cls,
        value: Any,
        document_type: str,
        file_name: str,
        page: Optional[int] = None,
        raw_text: Optional[str] = None,
        confidence: float = 1.0,
        extraction_method: str = "native_text",
        normalized_value: Optional[str] = None,
    ) -> "ExtractedField":
        ev = EvidenceSource(
            document_type=document_type,
            file_name=file_name,
            page=page,
            raw_text=raw_text or (str(value) if value is not None else None),
            confidence=confidence,
            extraction_method=extraction_method,
        )
        return cls(
            value=value,
            raw_value=str(value) if value is not None else None,
            normalized_value=normalized_value,
            evidence=ev,
        )
