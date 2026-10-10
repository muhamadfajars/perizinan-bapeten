"""FastAPI REST Service for BAPETEN Document Matching and Cross-Check Engine.

Provides HTTP REST endpoints for Laravel Web Application and evaluator services:
- POST /api/v1/evaluate: Upload documents and execute multi-entity cross-check & compliance
- POST /api/v1/evaluate-paths: Execute cross-check using existing file paths
- GET /api/v1/results/{run_id}: Retrieve past evaluation result
- GET /api/v1/schemas/{schema_name}: Retrieve JSON Schema definitions
- GET /health: Health check and service status
"""

import json
import shutil
from pathlib import Path
from uuid import uuid4
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from config import DATA_DIR, RESULT_DIR, DOCUMENT_TYPES
from src.pipeline import execute_run
from src.schema.exporter import export_schemas

app = FastAPI(
    title="BAPETEN Document Matching & Evaluation Engine",
    description="Python Document Intelligence & Cross-Check API for DPFRZR BAPETEN",
    version="1.0.0",
)

# Enable CORS for Laravel / Web App integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_BASE_DIR = DATA_DIR / "uploads"
UPLOAD_BASE_DIR.mkdir(parents=True, exist_ok=True)


class EvaluatePathsRequest(BaseModel):
    documents: Dict[str, List[str]] = Field(
        ...,
        description="Mapping of document_type to list of local absolute file paths",
        examples=[{
            "formulir": ["/path/to/Formulir.pdf"],
            "ppkr": ["/path/to/PPKR.pdf"],
            "label_unit": ["/path/to/label_unit.jpg"],
        }],
    )


@app.get("/", tags=["Info"])
def root():
    return {
        "service": "BAPETEN Document Matching & Evaluation Engine",
        "version": "1.0.0",
        "status": "online",
        "docs_url": "/docs",
    }


@app.get("/health", tags=["Health"])
def health():
    return {
        "status": "healthy",
        "supported_documents": list(DOCUMENT_TYPES.keys()),
        "output_directory": str(RESULT_DIR),
    }


@app.post("/api/v1/evaluate", tags=["Evaluation"])
async def evaluate_uploaded_documents(
    formulir: Optional[List[UploadFile]] = File(None),
    ppkr: Optional[List[UploadFile]] = File(None),
    label_unit: Optional[List[UploadFile]] = File(None),
    label_tabung: Optional[List[UploadFile]] = File(None),
    sip: Optional[List[UploadFile]] = File(None),
    sib: Optional[List[UploadFile]] = File(None),
    sprint: Optional[List[UploadFile]] = File(None),
    spesifikasi_pesawat: Optional[List[UploadFile]] = File(None),
    uji_kesesuaian: Optional[List[UploadFile]] = File(None),
    uji_fungsi: Optional[List[UploadFile]] = File(None),
    paparan_radiasi: Optional[List[UploadFile]] = File(None),
    tld: Optional[List[UploadFile]] = File(None),
    sistem_manajemen: Optional[List[UploadFile]] = File(None),
    program_perawatan: Optional[List[UploadFile]] = File(None),
    persetujuan_import: Optional[List[UploadFile]] = File(None),
):
    """Upload documents via multipart/form-data and perform end-to-end evaluation."""
    run_id = uuid4().hex[:12]
    run_upload_dir = UPLOAD_BASE_DIR / run_id
    run_upload_dir.mkdir(parents=True, exist_ok=True)

    uploads_map = {
        "formulir": formulir,
        "ppkr": ppkr,
        "label_unit": label_unit,
        "label_tabung": label_tabung,
        "sip": sip,
        "sib": sib,
        "sprint": sprint,
        "spesifikasi_pesawat": spesifikasi_pesawat,
        "uji_kesesuaian": uji_kesesuaian,
        "uji_fungsi": uji_fungsi,
        "paparan_radiasi": paparan_radiasi,
        "tld": tld,
        "sistem_manajemen": sistem_manajemen,
        "program_perawatan": program_perawatan,
        "persetujuan_import": persetujuan_import,
    }

    document_inputs = {}
    any_file_uploaded = False

    for doc_type, file_list in uploads_map.items():
        if not file_list:
            continue
        doc_dir = run_upload_dir / doc_type
        doc_dir.mkdir(parents=True, exist_ok=True)
        saved_paths = []
        for upload in file_list:
            if not upload.filename:
                continue
            dest_file = doc_dir / upload.filename
            with dest_file.open("wb") as buffer:
                shutil.copyfileobj(upload.file, buffer)
            saved_paths.append(dest_file)
            any_file_uploaded = True
        if saved_paths:
            document_inputs[doc_type] = saved_paths

    if not any_file_uploaded:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Minimal satu berkas permohonan harus diunggah (misal: formulir atau ppkr).",
        )

    try:
        result = execute_run(document_inputs)
        return result
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Terjadi kesalahan saat memproses dokumen: {str(exc)}",
        )


@app.post("/api/v1/evaluate-paths", tags=["Evaluation"])
def evaluate_from_paths(payload: EvaluatePathsRequest):
    """Execute evaluation given existing server-side file paths (e.g. shared volume with Laravel)."""
    document_inputs = {}
    for doc_type, paths in payload.documents.items():
        if doc_type not in DOCUMENT_TYPES:
            continue
        valid_paths = []
        for p in paths:
            path_obj = Path(p)
            if not path_obj.exists():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Berkas tidak ditemukan pada path: {p}",
                )
            valid_paths.append(path_obj)
        if valid_paths:
            document_inputs[doc_type] = valid_paths

    if not document_inputs:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tidak ada path berkas valid yang diberikan.",
        )

    try:
        result = execute_run(document_inputs)
        return result
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Kesalahan saat memproses dokumen: {str(exc)}",
        )


@app.get("/api/v1/results/{run_id}", tags=["Results"])
def get_evaluation_result(run_id: str):
    """Retrieve result JSON from a previously executed run."""
    result_file = RESULT_DIR / f"{run_id}.json"
    if not result_file.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Hasil evaluasi dengan run_id '{run_id}' tidak ditemukan.",
        )
    return json.loads(result_file.read_text(encoding="utf-8"))


@app.get("/api/v1/schemas/{schema_name}", tags=["Schemas"])
def get_json_schema(schema_name: str):
    """Retrieve standard JSON Schema definition for Laravel integration."""
    schema_dir = DATA_DIR / "schemas"
    if not schema_dir.exists():
        export_schemas()

    clean_name = schema_name.replace(".schema.json", "").replace(".json", "")
    target_file = schema_dir / f"{clean_name}.schema.json"
    if not target_file.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Schema '{schema_name}' tidak ditemukan. Tersedia: application_entity, cross_check_report, entity_cross_check, field_cross_check",
        )
    return json.loads(target_file.read_text(encoding="utf-8"))
