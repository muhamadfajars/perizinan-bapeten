"""Domain entity models for BAPETEN Document Matching System.

Supports multi-entity cardinality: 1 Application has many Personnel, many PPR,
and many X-Ray equipment units (each optionally paired with an X-Ray tube).
"""

from typing import List, Optional
from pydantic import BaseModel, Field

from src.schema.evidence import ExtractedField


class FacilityEntity(BaseModel):
    """Fasilitas / Rumah Sakit / Proyek."""
    id: str = Field(default="facility_1", description="Unique entity ID")
    project_name: ExtractedField[str] = Field(
        default_factory=ExtractedField, description="Nama proyek / fasilitas"
    )
    project_address: ExtractedField[str] = Field(
        default_factory=ExtractedField, description="Alamat proyek / fasilitas"
    )
    institution_name: Optional[ExtractedField[str]] = Field(
        default=None, description="Nama instansi pemohon"
    )
    institution_address: Optional[ExtractedField[str]] = Field(
        default=None, description="Alamat instansi pemohon"
    )


class PersonnelEntity(BaseModel):
    """Personel / Petugas Medis / Radiografer / Dokter Spesialis."""
    id: str = Field(..., description="Unique person entity ID, e.g. person_1")
    name: ExtractedField[str] = Field(
        default_factory=ExtractedField, description="Nama personel"
    )
    profession: ExtractedField[str] = Field(
        default_factory=ExtractedField, description="Profesi / keahlian (Dokter Spesialis Radiologi, Radiografer, dll)"
    )
    npr: Optional[ExtractedField[str]] = Field(
        default=None, description="Nomor Pekerja Radiasi (NPR / NRP)"
    )
    sip_number: Optional[ExtractedField[str]] = Field(
        default=None, description="Nomor SIP (Surat Izin Praktik)"
    )
    valid_until: Optional[ExtractedField[str]] = Field(
        default=None, description="Masa berlaku SIP"
    )
    practice_location: Optional[ExtractedField[str]] = Field(
        default=None, description="Tempat praktik tercantum pada SIP"
    )


class PPREntity(BaseModel):
    """Petugas Proteksi Radiasi (PPR)."""
    id: str = Field(..., description="Unique PPR entity ID, e.g. ppr_1")
    name: ExtractedField[str] = Field(
        default_factory=ExtractedField, description="Nama PPR"
    )
    sib_number: Optional[ExtractedField[str]] = Field(
        default=None, description="Nomor Surat Izin Bekerja (SIB)"
    )
    valid_until: Optional[ExtractedField[str]] = Field(
        default=None, description="Masa berlaku SIB"
    )
    appointment_letter_number: Optional[ExtractedField[str]] = Field(
        default=None, description="Nomor Surat Perintah / SK Penunjukan PPR (Sprint)"
    )


class XRayTubeEntity(BaseModel):
    """Tabung Sinar-X (X-Ray Tube)."""
    id: str = Field(..., description="Unique tube entity ID, e.g. tube_1")
    tube_brand: ExtractedField[str] = Field(
        default_factory=ExtractedField, description="Merk tabung sinar-X (e.g. TOSHIBA, CANON, VARIAN)"
    )
    tube_type: ExtractedField[str] = Field(
        default_factory=ExtractedField, description="Tipe tabung sinar-X"
    )
    tube_model: ExtractedField[str] = Field(
        default_factory=ExtractedField, description="Model tabung (unit model / insert model / housing model)"
    )
    tube_serial_number: ExtractedField[str] = Field(
        default_factory=ExtractedField, description="Nomor seri tabung sinar-X"
    )


class XRayEquipmentEntity(BaseModel):
    """Unit Pesawat Sinar-X."""
    id: str = Field(..., description="Unique equipment unit entity ID, e.g. unit_1")
    unit_brand: ExtractedField[str] = Field(
        default_factory=ExtractedField, description="Merk unit pesawat sinar-X"
    )
    unit_type: ExtractedField[str] = Field(
        default_factory=ExtractedField, description="Tipe pesawat sinar-X"
    )
    unit_serial_number: ExtractedField[str] = Field(
        default_factory=ExtractedField, description="Nomor seri unit pesawat sinar-X"
    )
    max_condition: Optional[ExtractedField[str]] = Field(
        default=None, description="Kondisi maksimum operasional (kV / mA)"
    )
    tube: Optional[XRayTubeEntity] = Field(
        default=None, description="Tabung sinar-X terpasang pada unit ini"
    )


class AdministrativeDocument(BaseModel):
    """Catatan dokumen kelengkapan administrasi yang terdaftar di formulir."""
    requirement: str = Field(..., description="Nama persyaratan / dokumen")
    document_number: Optional[str] = Field(default=None, description="Nomor dokumen")
    document_date: Optional[str] = Field(default=None, description="Tanggal dokumen")


class ApplicationEntity(BaseModel):
    """Entitas Permohonan Lengkap (Container Hasil Ekstraksi Seluruh Dokumen)."""
    application_id: str = Field(default="", description="ID permohonan atau nomor registrasi")
    registration_number: Optional[str] = Field(default=None, description="Nomor registrasi BAPETEN")
    registration_date: Optional[str] = Field(default=None, description="Tanggal registrasi")
    scope: Optional[str] = Field(default=None, description="Lingkup kegiatan")
    facility: FacilityEntity = Field(default_factory=FacilityEntity, description="Data fasilitas")
    personnel: List[PersonnelEntity] = Field(default_factory=list, description="Daftar personel")
    ppr: List[PPREntity] = Field(default_factory=list, description="Daftar PPR")
    xray_equipment: List[XRayEquipmentEntity] = Field(default_factory=list, description="Daftar pesawat sinar-X")
    administrative_documents: List[AdministrativeDocument] = Field(
        default_factory=list, description="Daftar dokumen kelengkapan administrasi"
    )
