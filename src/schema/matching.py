"""Cross-check and matching result schemas for BAPETEN Document Matching System.

Designed to provide structured JSON ready for consumption by Laravel UI,
evaluators, and API endpoints, fulfilling:
- Exact multi-entity cross-check hierarchy
- Source document & page attribution
- Full evidence tracking (preview / snippet / bbox)
- Status (SESUAI, PERLU REVIEW, TIDAK SESUAI, TIDAK DITEMUKAN)
- Detailed explanation / reasoning for decision
"""

from enum import Enum
from typing import Any, Dict, List, Optional, Union
from datetime import datetime, timezone
from pydantic import BaseModel, Field, ConfigDict, model_validator


class MatchingStatus(str, Enum):
    """Standar status evaluasi cross-check."""
    SESUAI = "SESUAI"
    PERLU_REVIEW = "PERLU REVIEW"
    TIDAK_SESUAI = "TIDAK SESUAI"
    TIDAK_DITEMUKAN = "TIDAK DITEMUKAN"
    WARNING = "WARNING"


class SourceEvidence(BaseModel):
    """Informasi dokumen sumber untuk suatu nilai field."""
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="ignore")

    document_type: str = Field(..., description="Tipe dokumen (e.g. formulir, ppkr, label_unit, sip, sib)")
    document_name: str = Field(..., description="Nama file dokumen")
    page: Optional[int] = Field(default=None, description="Halaman ditemukannya nilai (1-indexed)")
    value: str = Field(..., description="Nilai yang diekstraksi dari dokumen ini")
    raw_text: Optional[str] = Field(default=None, description="Potongan teks / konteks mentah (evidence snippet)")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Tingkat kepercayaan ekstraksi/OCR")
    bbox: Optional[List[float]] = Field(default=None, description="Bounding box koordinat jika berbasis gambar/OCR")


class FieldCrossCheck(BaseModel):
    """Hasil cross-check untuk satu field tertentu antar beberapa dokumen."""
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="ignore")

    field_key: str = Field(..., description="Identifikasi field, misal unit_serial_number")
    field_label: str = Field(..., description="Label manusia, misal Nomor Seri Unit")
    status: MatchingStatus = Field(..., description="Status kesesuaian")
    score: Optional[float] = Field(default=None, ge=0.0, le=100.0, description="Skor kemiripan / similarity (0-100)")
    reason: Optional[str] = Field(default=None, description="Penjelasan mengapa status ini diberikan")
    sources: List[SourceEvidence] = Field(default_factory=list, description="Daftar nilai dari dokumen-dokumen pembanding")
    discrepancies: List[str] = Field(default_factory=list, description="Detail perbedaan jika ada ketidaksesuaian")

    @model_validator(mode="before")
    @classmethod
    def normalize_sources(cls, data: Any) -> Any:
        if isinstance(data, dict) and "sources" in data and isinstance(data["sources"], list):
            norm = []
            for s in data["sources"]:
                if hasattr(s, "model_dump"):
                    norm.append(s.model_dump())
                elif hasattr(s, "dict"):
                    norm.append(s.dict())
                elif hasattr(s, "__dict__"):
                    norm.append(s.__dict__)
                else:
                    norm.append(s)
            data["sources"] = norm
        return data


class EntityCrossCheck(BaseModel):
    """Hasil cross-check untuk satu entitas (Fasilitas, 1 Personel, 1 PPR, atau 1 Pesawat Sinar-X)."""
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="ignore")

    category: str = Field(..., description="Kategori entitas: facility | personnel | ppr | xray_equipment | tube")
    entity_id: str = Field(..., description="ID entitas, misal unit_1, person_1")
    entity_label: str = Field(..., description="Label ringkas entitas, misal 'Unit #1: SHIMADZU SB2002000027WK'")
    status: MatchingStatus = Field(..., description="Status kumulatif entitas")
    fields: Dict[str, FieldCrossCheck] = Field(default_factory=dict, description="Pemeriksaan field-field pada entitas ini")
    sub_entities: List["EntityCrossCheck"] = Field(
        default_factory=list, description="Sub-entitas terkait, misal Tabung Sinar-X di dalam Pesawat Sinar-X"
    )


class MatchSummary(BaseModel):
    """Ringkasan statistik hasil cross-check."""
    total_fields_checked: int = Field(default=0, description="Total field yang dievaluasi")
    sesuai: int = Field(default=0, description="Jumlah field dengan status SESUAI")
    perlu_review: int = Field(default=0, description="Jumlah field dengan status PERLU REVIEW")
    tidak_sesuai: int = Field(default=0, description="Jumlah field dengan status TIDAK SESUAI")
    tidak_ditemukan: int = Field(default=0, description="Jumlah field dengan status TIDAK DITEMUKAN")
    warning: int = Field(default=0, description="Jumlah field dengan status WARNING")


class CrossCheckReport(BaseModel):
    """Laporan Evaluasi & Cross-Check Lengkap Permohonan BAPETEN.
    
    Ini adalah struktur data final yang dihasilkan oleh Python processing engine
    dan dikirimkan ke Laravel Web Application untuk ditampilkan kepada evaluator.
    """
    run_id: str = Field(..., description="Unique run/job execution ID")
    application_id: Optional[str] = Field(default=None, description="ID permohonan atau nomor registrasi BAPETEN")
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="Waktu pembuatan laporan ISO 8601"
    )
    facility: Optional[EntityCrossCheck] = Field(
        default=None, description="1. Identitas Fasilitas (Nama instansi, Alamat instansi)"
    )
    personnel: List[EntityCrossCheck] = Field(
        default_factory=list, description="2. Personel (Nama, Profesi/Keahlian, Nama PPR, Masa berlaku, Tempat praktik)"
    )
    ppr: List[EntityCrossCheck] = Field(
        default_factory=list, description="Daftar Petugas Proteksi Radiasi (PPR)"
    )
    xray_equipment: List[EntityCrossCheck] = Field(
        default_factory=list, description="3. Pesawat Sinar-X (Merk unit, Tipe unit, Nomor seri unit)"
    )
    xray_tubes: List[EntityCrossCheck] = Field(
        default_factory=list, description="4. Tabung Sinar-X (Merk tabung, Tipe/model tabung, Nomor seri tabung)"
    )
    summary: MatchSummary = Field(
        default_factory=MatchSummary, description="Ringkasan statistik status"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Metadata proses, seperti daftar file diproses, versi pipeline, durasi"
    )
