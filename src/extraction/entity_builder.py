"""Entity Builder and Consolidation Engine.

Consolidates multi-document extractions into a unified ApplicationEntity
supporting 1-to-many cardinality (multiple personnel, multiple PPRs,
multiple X-ray units & tubes).
"""

from typing import Any, Dict, List, Optional
from rapidfuzz import fuzz

from src.matching.normalizer import normalize, normalize_serial
from src.schema.evidence import ExtractedField, EvidenceSource
from src.schema.entities import (
    ApplicationEntity,
    FacilityEntity,
    PersonnelEntity,
    PPREntity,
    XRayEquipmentEntity,
    XRayTubeEntity,
    AdministrativeDocument,
)
from src.extraction.form_parser import build_application_from_form


def _get_val(field_dict_or_val: Any) -> str:
    if isinstance(field_dict_or_val, dict):
        v = str(field_dict_or_val.get("value") or "").strip()
    else:
        v = str(field_dict_or_val or "").strip()
    return "" if v in ("-", "—") else v


def _get_page(field_dict: Any) -> Optional[int]:
    if isinstance(field_dict, dict):
        return field_dict.get("page")
    return None


def _get_raw(field_dict: Any) -> Optional[str]:
    if isinstance(field_dict, dict):
        return field_dict.get("raw_text") or str(field_dict.get("value") or "")
    return str(field_dict or "") if field_dict else None


def find_best_person_match(
    name: str,
    personnel_list: List[PersonnelEntity],
    threshold: float = 75.0,
) -> Optional[PersonnelEntity]:
    """Finds the most matching PersonnelEntity in the list based on normalized name similarity."""
    if not name or not personnel_list:
        return None
    norm_query = normalize(name)
    best_person = None
    best_score = 0.0

    for p in personnel_list:
        p_name = p.name.value or ""
        norm_p = normalize(p_name)
        if norm_query == norm_p:
            return p
        score = fuzz.token_sort_ratio(norm_query, norm_p)
        if score > best_score and score >= threshold:
            best_score = score
            best_person = p

    return best_person


def find_best_ppr_match(
    name: str,
    ppr_list: List[PPREntity],
    threshold: float = 75.0,
) -> Optional[PPREntity]:
    """Finds matching PPREntity based on name."""
    if not name or not ppr_list:
        return None
    norm_query = normalize(name)
    best_ppr = None
    best_score = 0.0

    for ppr in ppr_list:
        p_name = ppr.name.value or ""
        norm_p = normalize(p_name)
        if norm_query == norm_p:
            return ppr
        score = fuzz.token_sort_ratio(norm_query, norm_p)
        if score > best_score and score >= threshold:
            best_score = score
            best_ppr = ppr

    return best_ppr


def find_best_equipment_match(
    serial: str,
    brand: str,
    unit_type: str,
    equipment_list: List[XRayEquipmentEntity],
) -> Optional[XRayEquipmentEntity]:
    """Finds matching XRayEquipmentEntity based on serial number, or brand + type."""
    if not equipment_list:
        return None

    # Priority 1: Match by normalized serial number if present
    if serial:
        norm_serial = normalize_serial(serial)
        for eq in equipment_list:
            eq_sn = eq.unit_serial_number.value
            if eq_sn and normalize_serial(eq_sn) == norm_serial:
                return eq

    # Priority 2: Match by brand and type
    norm_b = normalize(brand)
    norm_t = normalize(unit_type)
    for eq in equipment_list:
        eq_b = normalize(eq.unit_brand.value or "")
        eq_t = normalize(eq.unit_type.value or "")
        if norm_b and eq_b and (norm_b in eq_b or eq_b in norm_b):
            if norm_t and eq_t and fuzz.token_sort_ratio(norm_t, eq_t) >= 70:
                return eq

    # Priority 3: If only 1 equipment unit exists, return it
    if len(equipment_list) == 1:
        return equipment_list[0]

    return None


def consolidate_application(extractions: Dict[str, List[Dict[str, Any]]]) -> ApplicationEntity:
    """Consolidates extractions across all uploaded documents into a master ApplicationEntity.

    - Uses Formulir Permohonan as primary anchor if present.
    - Consolidates SIP into Personnel.
    - Consolidates SIB and Sprint into PPR.
    - Consolidates Unit Labels, Tube Labels, Specs, Import Approvals, and Conformity Tests into XRayEquipment.
    """
    app: Optional[ApplicationEntity] = None

    # 1. Anchor from Formulir if available
    formulir_docs = extractions.get("formulir", [])
    if formulir_docs:
        form_doc = formulir_docs[0]
        parsed_fields = form_doc.get("fields", {})
        # Check if form_doc has raw parsed structure or fields
        file_name = form_doc.get("file_name", "Formulir_Permohonan.pdf")
        all_xr = parsed_fields.get("all_xray_rows", [])
        if isinstance(all_xr, dict):
            all_xr = all_xr.get("value", [])
        if not all_xr:
            xr_fallback = {
                "unit_brand": _get_val(parsed_fields.get("unit_brand")),
                "unit_type": _get_val(parsed_fields.get("unit_type")),
                "unit_serial_number": _get_val(parsed_fields.get("unit_serial_number")),
                "tube_brand": _get_val(parsed_fields.get("tube_brand")),
                "tube_type": _get_val(parsed_fields.get("tube_type")),
                "tube_serial_number": _get_val(parsed_fields.get("tube_serial_number")),
            }
            if any(xr_fallback.values()):
                all_xr = [xr_fallback]

        raw_pdata = parsed_fields.get("personnel_data", [])
        if isinstance(raw_pdata, dict) and "value" in raw_pdata:
            raw_pdata = raw_pdata["value"]
        if isinstance(raw_pdata, str):
            raw_pdata = [line.strip() for line in raw_pdata.split("\n") if line.strip()]
        elif not isinstance(raw_pdata, list):
            raw_pdata = [raw_pdata] if raw_pdata else []

        raw_admin = parsed_fields.get("administrative_documents", [])
        if isinstance(raw_admin, dict) and "value" in raw_admin:
            raw_admin = raw_admin["value"]
        if not isinstance(raw_admin, list):
            raw_admin = [raw_admin] if raw_admin else []

        form_dict = {
            "header": parsed_fields.get("header", {}),
            "hospital_name": parsed_fields.get("hospital_name", {}),
            "hospital_address": parsed_fields.get("hospital_address", {}),
            "personnel_data": raw_pdata,
            "administrative_documents": raw_admin,
            "all_xray_rows": all_xr,
        }
        app = build_application_from_form(form_dict, file_name=file_name)
    else:
        app = ApplicationEntity(application_id="APP-NO-FORMULIR")

    # 2. Consolidate PPKR if available (can complement facility, personnel, and equipment)
    ppkr_docs = extractions.get("ppkr", [])
    for doc_type in ["ppkr", "uji_kesesuaian", "paparan_radiasi", "sprint"]:
        for doc in extractions.get(doc_type, []):
            f = doc.get("fields", {})
            file_name = doc.get("file_name", f"{doc_type}.pdf")

            # Facility complement if missing in app
            if not app.facility.project_name.value and f.get("hospital_name") and _get_val(f.get("hospital_name")):
                app.facility.project_name = ExtractedField[str].from_value(
                    value=_get_val(f.get("hospital_name")),
                    document_type=doc_type,
                    file_name=file_name,
                    page=_get_page(f.get("hospital_name")),
                )
            if not app.facility.project_address.value and f.get("hospital_address") and _get_val(f.get("hospital_address")):
                app.facility.project_address = ExtractedField[str].from_value(
                    value=_get_val(f.get("hospital_address")),
                    document_type=doc_type,
                    file_name=file_name,
                    page=_get_page(f.get("hospital_address")),
                )

    for doc in ppkr_docs:
        f = doc.get("fields", {})
        file_name = doc.get("file_name", "PPKR.pdf")

        # Equipment complement from PPKR if equipment list is empty
        if not app.xray_equipment and any([f.get("unit_brand"), f.get("unit_type"), f.get("unit_serial_number")]):
            tube = None
            if any([f.get("tube_brand"), f.get("tube_type")]):
                tube = XRayTubeEntity(
                    id="tube_ppkr_1",
                    tube_brand=ExtractedField[str].from_value(
                        value=_get_val(f.get("tube_brand")),
                        document_type="ppkr",
                        file_name=file_name,
                        page=_get_page(f.get("tube_brand")),
                    ),
                    tube_type=ExtractedField[str].from_value(
                        value=_get_val(f.get("tube_type")),
                        document_type="ppkr",
                        file_name=file_name,
                        page=_get_page(f.get("tube_type")),
                    ),
                    tube_model=ExtractedField[str].from_value(
                        value=_get_val(f.get("tube_type")),
                        document_type="ppkr",
                        file_name=file_name,
                        page=_get_page(f.get("tube_type")),
                    ),
                    tube_serial_number=ExtractedField[str].from_value(
                        value=_get_val(f.get("tube_serial_number")),
                        document_type="ppkr",
                        file_name=file_name,
                        page=_get_page(f.get("tube_serial_number")),
                    ),
                )
            eq = XRayEquipmentEntity(
                id="unit_ppkr_1",
                unit_brand=ExtractedField[str].from_value(
                    value=_get_val(f.get("unit_brand")),
                    document_type="ppkr",
                    file_name=file_name,
                    page=_get_page(f.get("unit_brand")),
                ),
                unit_type=ExtractedField[str].from_value(
                    value=_get_val(f.get("unit_type")),
                    document_type="ppkr",
                    file_name=file_name,
                    page=_get_page(f.get("unit_type")),
                ),
                unit_serial_number=ExtractedField[str].from_value(
                    value=_get_val(f.get("unit_serial_number")),
                    document_type="ppkr",
                    file_name=file_name,
                    page=_get_page(f.get("unit_serial_number")),
                ),
                tube=tube,
            )
            app.xray_equipment.append(eq)

    # 3. Consolidate SIP into Personnel
    sip_docs = extractions.get("sip", [])
    for doc in sip_docs:
        f = doc.get("fields", {})
        file_name = doc.get("file_name", "SIP.pdf")
        sip_name = _get_val(f.get("person_name"))
        sip_prof = _get_val(f.get("profession"))
        sip_valid = _get_val(f.get("valid_until"))
        sip_loc = _get_val(f.get("practice_location"))
        sip_page = _get_page(f.get("person_name"))

        matched_person = find_best_person_match(sip_name, app.personnel)
        if matched_person:
            # Enrich existing personnel
            if sip_valid and not matched_person.valid_until:
                matched_person.valid_until = ExtractedField[str].from_value(
                    value=sip_valid,
                    document_type="sip",
                    file_name=file_name,
                    page=_get_page(f.get("valid_until")),
                )
            if sip_loc and not matched_person.practice_location:
                matched_person.practice_location = ExtractedField[str].from_value(
                    value=sip_loc,
                    document_type="sip",
                    file_name=file_name,
                    page=_get_page(f.get("practice_location")),
                )
        else:
            # New personnel discovered from SIP
            new_p = PersonnelEntity(
                id=f"person_sip_{len(app.personnel) + 1}",
                name=ExtractedField[str].from_value(
                    value=sip_name,
                    document_type="sip",
                    file_name=file_name,
                    page=sip_page,
                ),
                profession=ExtractedField[str].from_value(
                    value=sip_prof,
                    document_type="sip",
                    file_name=file_name,
                    page=_get_page(f.get("profession")),
                ),
                valid_until=ExtractedField[str].from_value(
                    value=sip_valid,
                    document_type="sip",
                    file_name=file_name,
                    page=_get_page(f.get("valid_until")),
                ) if sip_valid else None,
                practice_location=ExtractedField[str].from_value(
                    value=sip_loc,
                    document_type="sip",
                    file_name=file_name,
                    page=_get_page(f.get("practice_location")),
                ) if sip_loc else None,
            )
            app.personnel.append(new_p)

    # 4. Consolidate SIB and Sprint into PPR
    sib_docs = extractions.get("sib", [])
    for doc in sib_docs:
        f = doc.get("fields", {})
        file_name = doc.get("file_name", "SIB.pdf")
        sib_name = _get_val(f.get("ppr_name")) or _get_val(f.get("person_name"))
        sib_valid = _get_val(f.get("valid_until"))

        matched_ppr = find_best_ppr_match(sib_name, app.ppr)
        if matched_ppr:
            if sib_valid and not matched_ppr.valid_until:
                matched_ppr.valid_until = ExtractedField[str].from_value(
                    value=sib_valid,
                    document_type="sib",
                    file_name=file_name,
                    page=_get_page(f.get("valid_until")),
                )
        elif sib_name:
            new_ppr = PPREntity(
                id=f"ppr_sib_{len(app.ppr) + 1}",
                name=ExtractedField[str].from_value(
                    value=sib_name,
                    document_type="sib",
                    file_name=file_name,
                    page=_get_page(f.get("ppr_name")) or _get_page(f.get("person_name")),
                ),
                valid_until=ExtractedField[str].from_value(
                    value=sib_valid,
                    document_type="sib",
                    file_name=file_name,
                    page=_get_page(f.get("valid_until")),
                ) if sib_valid else None,
            )
            app.ppr.append(new_ppr)

    # 5. Consolidate Unit Labels into XRayEquipment
    label_unit_docs = extractions.get("label_unit", [])
    for doc in label_unit_docs:
        f = doc.get("fields", {})
        file_name = doc.get("file_name", "Label_Unit.jpg")
        brand = _get_val(f.get("unit_brand"))
        u_type = _get_val(f.get("unit_type"))
        serial = _get_val(f.get("unit_serial_number"))

        matched_eq = find_best_equipment_match(serial, brand, u_type, app.xray_equipment)
        if not matched_eq:
            # Create a new unit if not matching any
            new_eq = XRayEquipmentEntity(
                id=f"unit_label_{len(app.xray_equipment) + 1}",
                unit_brand=ExtractedField[str].from_value(
                    value=brand,
                    document_type="label_unit",
                    file_name=file_name,
                    page=1,
                    extraction_method="ocr",
                ),
                unit_type=ExtractedField[str].from_value(
                    value=u_type,
                    document_type="label_unit",
                    file_name=file_name,
                    page=1,
                    extraction_method="ocr",
                ),
                unit_serial_number=ExtractedField[str].from_value(
                    value=serial,
                    document_type="label_unit",
                    file_name=file_name,
                    page=1,
                    extraction_method="ocr",
                ),
            )
            app.xray_equipment.append(new_eq)

    # 6. Consolidate Tube Labels into XRayTube
    label_tube_docs = extractions.get("label_tabung", [])
    for doc in label_tube_docs:
        f = doc.get("fields", {})
        file_name = doc.get("file_name", "Label_Tabung.jpg")
        brand = _get_val(f.get("tube_brand"))
        model = _get_val(f.get("tube_unit_model")) or _get_val(f.get("tube_insert_model"))
        serial = _get_val(f.get("tube_serial_number"))

        # Find first unit without tube or matching tube
        attached = False
        for eq in app.xray_equipment:
            if eq.tube and eq.tube.tube_serial_number.value:
                if normalize_serial(eq.tube.tube_serial_number.value) == normalize_serial(serial):
                    attached = True
                    break
            elif eq.tube is None:
                eq.tube = XRayTubeEntity(
                    id=f"tube_label_{eq.id}",
                    tube_brand=ExtractedField[str].from_value(
                        value=brand,
                        document_type="label_tabung",
                        file_name=file_name,
                        page=1,
                        extraction_method="ocr",
                    ),
                    tube_type=ExtractedField[str].from_value(
                        value=model,
                        document_type="label_tabung",
                        file_name=file_name,
                        page=1,
                        extraction_method="ocr",
                    ),
                    tube_model=ExtractedField[str].from_value(
                        value=model,
                        document_type="label_tabung",
                        file_name=file_name,
                        page=1,
                        extraction_method="ocr",
                    ),
                    tube_serial_number=ExtractedField[str].from_value(
                        value=serial,
                        document_type="label_tabung",
                        file_name=file_name,
                        page=1,
                        extraction_method="ocr",
                    ),
                )
                attached = True
                break

    return app
