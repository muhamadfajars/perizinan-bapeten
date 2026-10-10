"""Master schema package for BAPETEN Document Matching System."""

from .fields import (
    DOCUMENT_TYPES,
    FIELD_DEFINITIONS,
    CANONICAL_GROUPS,
    CROSS_CHECK_RULES,
    DOCUMENT_FIELDS,
)
from .evidence import EvidenceSource, ExtractedField
from .entities import (
    FacilityEntity,
    PersonnelEntity,
    PPREntity,
    XRayTubeEntity,
    XRayEquipmentEntity,
    AdministrativeDocument,
    ApplicationEntity,
)
from .matching import (
    MatchingStatus,
    SourceEvidence,
    FieldCrossCheck,
    EntityCrossCheck,
    MatchSummary,
    CrossCheckReport,
)
from .exporter import export_schemas

__all__ = [
    # Document and field definitions
    "DOCUMENT_TYPES",
    "FIELD_DEFINITIONS",
    "CANONICAL_GROUPS",
    "CROSS_CHECK_RULES",
    "DOCUMENT_FIELDS",
    # Evidence models
    "EvidenceSource",
    "ExtractedField",
    # Domain entities
    "FacilityEntity",
    "PersonnelEntity",
    "PPREntity",
    "XRayTubeEntity",
    "XRayEquipmentEntity",
    "AdministrativeDocument",
    "ApplicationEntity",
    # Matching and cross-check report models
    "MatchingStatus",
    "SourceEvidence",
    "FieldCrossCheck",
    "EntityCrossCheck",
    "MatchSummary",
    "CrossCheckReport",
    # Utilities
    "export_schemas",
]
