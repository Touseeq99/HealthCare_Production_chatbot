"""
AI Clinical Note — FastAPI Router
==================================
Exposes the /api/clinical-note/generate endpoint (doctor-only).

Endpoint:  POST /api/clinical-note/generate
Auth:      Bearer token (doctor role enforced)
Response:  JSON following the AI Clinical Note schema
"""

from fastapi import APIRouter, Request, Depends, status, HTTPException, File, UploadFile, Form
from pydantic import BaseModel, Field, validator
from typing import Optional, List, Literal
from utils.auth_dependencies import get_current_user
from utils.clinical_note_engine import generate_clinical_note
from utils.error_handler import AppException, ExternalServiceError, AuthorizationError
from utils.logger import get_request_id
from utils.validation import SQLInjectionProtection, ValidationMiddleware
from slowapi import Limiter
from slowapi.util import get_remote_address
from config import settings
from typing import Any
import logging
from utils.file_extractor import extract_text_from_upload, validate_upload

logger = logging.getLogger(__name__)
limiter = Limiter(key_func=get_remote_address)
router = APIRouter()


# ---------------------------------------------------------------------------
# Request / Response Pydantic models
# ---------------------------------------------------------------------------

class ClinicalNoteOptions(BaseModel):
    """Optional behavioural flags for note generation."""
    include_ecg: bool = False
    include_labs: bool = False
    use_guidelines: bool = True
    conservative_wording: bool = True
    include_differential: bool = False


class ClinicalNoteRequest(BaseModel):
    """
    Input schema for the AI Clinical Note endpoint.

    Fields
    ------
    note_type       : One of SOAP | Progress Note | Discharge Summary |
                      Referral Letter | OPD Note
    raw_input       : Doctor's raw text, bullets, shorthand, or voice-
                      transcribed notes (required)
    ecg_data        : ECG text interpretation (optional)
    lab_data        : Lab result text (optional)
    options         : Behavioural flags (all optional, default-safe)
    """
    note_type: Literal[
        "SOAP",
        "PROGRESS",
        "DISCHARGE",
        "REFERRAL",
        "OPD",
    ] = Field(default="SOAP", description="Type of clinical note to generate")

    @validator("note_type", pre=True)
    def normalize_note_type(cls, v):
        if not v:
            return "SOAP"
        # Mapping table for display names to internal codes
        mapping = {
            "soap note": "SOAP",
            "progress note": "PROGRESS",
            "discharge summary": "DISCHARGE",
            "referral letter": "REFERRAL",
            "opd note": "OPD",
            "soap": "SOAP",
            "progress": "PROGRESS",
            "discharge": "DISCHARGE",
            "referral": "REFERRAL",
            "opd": "OPD"
        }
        val = str(v).strip().lower()
        if val in mapping:
            return mapping[val]
        return val.upper()

    raw_input: str = Field(
        ...,
        min_length=5,
        max_length=8000,
        description="Raw clinical text, shorthand, or voice-transcribed notes",
    )

    ecg_data: Optional[str] = Field(
        default=None,
        max_length=3000,
        description="ECG text interpretation (used only if options.include_ecg=true)",
    )

    lab_data: Optional[str] = Field(
        default=None,
        max_length=3000,
        description="Lab result text (used only if options.include_labs=true)",
    )

    options: ClinicalNoteOptions = Field(default_factory=ClinicalNoteOptions)

    @validator("raw_input")
    def sanitize_raw_input(cls, v):
        # Basic safety — strip leading/trailing whitespace
        return v.strip()

    @validator("ecg_data", "lab_data")
    def sanitize_optional_text(cls, v):
        if v:
            return v.strip()
        return v


class ClinicalNoteResponse(BaseModel):
    """Response schema — mirrors the AI Clinical Note output spec."""
    note_type: str
    generated_note: str
    sections: dict
    warnings: List[str]
    disclaimer: str


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.post(
    "/clinical-note/generate",
    response_model=ClinicalNoteResponse,
    status_code=status.HTTP_200_OK,
    summary="Generate a structured clinical note from raw doctor input",
    description=(
        "Transforms raw clinical input (shorthand, bullets, voice text) into a "
        "structured, legally-safe medical note. The generated note MUST be reviewed "
        "and approved by the treating physician before any clinical or legal use."
    ),
    tags=["Clinical Notes"],
)
@limiter.limit(f"{settings.RATE_LIMIT * 2}/minute")
async def generate_note(
    request: Request,
    body: ClinicalNoteRequest,
    current_user: Any = Depends(get_current_user),
):
    """
    Generate a structured clinical note.

    - **Doctor role required** — returns 403 if the authenticated user is not a doctor or admin.
    - Rate-limited to 2× the global RATE_LIMIT per minute.
    - Returns JSON conforming to the AI Clinical Note output spec.
    """
    # ---- Role enforcement ------------------------------------------------
    user_role = getattr(current_user, "role", None)
    if user_role not in ("doctor", "admin"):
        raise AuthorizationError(
            "Access denied. Clinical note generation is restricted to doctors and admins."
        )

    # ---- Request-level validation ----------------------------------------
    await ValidationMiddleware.validate_request_size(request, max_size_mb=1)
    await ValidationMiddleware.validate_content_type(request, ["application/json"])

    # SQL-injection guard on free-text fields
    SQLInjectionProtection.validate_input_safety(body.raw_input)
    if body.ecg_data:
        SQLInjectionProtection.validate_input_safety(body.ecg_data)
    if body.lab_data:
        SQLInjectionProtection.validate_input_safety(body.lab_data)

    # ---- Build engine payload --------------------------------------------
    payload = {
        "note_type": body.note_type,
        "raw_input": body.raw_input,
        "ecg_data": body.ecg_data,
        "lab_data": body.lab_data,
        "options": body.options.dict(),
    }

    logger.info(
        "Clinical note request received",
        extra={
            "request_id": get_request_id(),
            "note_type": body.note_type,
            "user_id": getattr(current_user, "id", "unknown"),
            "raw_input_len": len(body.raw_input),
            "include_ecg": body.options.include_ecg,
            "include_labs": body.options.include_labs,
            "include_differential": body.options.include_differential,
        },
    )

    # ---- Call the engine -------------------------------------------------
    try:
        result = await generate_clinical_note(payload)
    except Exception as exc:
        logger.error(
            f"Clinical note generation failed: {exc}",
            exc_info=True,
            extra={"request_id": get_request_id()},
        )
        raise ExternalServiceError("OpenAI", str(exc))

    return ClinicalNoteResponse(**result)

@router.post(
    "/clinical-note/upload",
    response_model=ClinicalNoteResponse,
    status_code=status.HTTP_200_OK,
    summary="Generate clinical note from text and/or files (PDF/Image)",
    description=(
        "Standard multi-modal endpoint. You can provide clinical history, ECG data, and "
        "Lab data as either raw text OR uploaded files. If a file is provided for a "
        "section, it takes precedence over the text for that section."
    ),
    tags=["Clinical Notes"],
)
@limiter.limit(f"{settings.RATE_LIMIT}/minute")
async def upload_note(
    request: Request,
    note_type: Optional[str] = Form("SOAP"),
    raw_input: Optional[str] = Form(None),
    ecg_data: Optional[str] = Form(None),
    lab_data: Optional[str] = Form(None),
    include_ecg: bool = Form(False),
    include_labs: bool = Form(False),
    include_differential: bool = Form(False),
    clinical_file: Optional[UploadFile] = File(None),
    ecg_file: Optional[UploadFile] = File(None),
    lab_file: Optional[UploadFile] = File(None),
    current_user: Any = Depends(get_current_user),
):
    """
    Hybrid Clinical Note endpoint (Text + Files).
    """
    user_role = getattr(current_user, "role", None)
    if user_role not in ("doctor", "admin"):
        raise AuthorizationError("Access denied.")

    final_raw_input = raw_input or ""
    final_ecg_data = ecg_data or ""
    final_lab_data = lab_data or ""
    extraction_warnings = []

    async def process_file(file: UploadFile, label: str):
        content = await file.read()
        validate_upload(file.filename, file.content_type, len(content))
        text, method = await extract_text_from_upload(content, file.content_type, file.filename)
        if method in ("pdf_vision_ocr", "image_vision"):
            extraction_warnings.append(f"{label} extracted via AI Vision. Please verify transcription.")
        return text

    # Precedence logic: File > Text
    if clinical_file and clinical_file.filename:
        final_raw_input = await process_file(clinical_file, "Clinical History")
    if ecg_file and ecg_file.filename:
        final_ecg_data = await process_file(ecg_file, "ECG Findings")
    if lab_file and lab_file.filename:
        final_lab_data = await process_file(lab_file, "Lab Results")

    if not final_raw_input.strip() and not final_ecg_data.strip() and not final_lab_data.strip():
        raise HTTPException(status_code=400, detail="No clinical data provided (neither text nor files).")

    payload = {
        "note_type": note_type,
        "raw_input": final_raw_input,
        "ecg_data": final_ecg_data,
        "lab_data": final_lab_data,
        "options": {
            "include_ecg": include_ecg or bool(final_ecg_data),
            "include_labs": include_labs or bool(final_lab_data),
            "include_differential": include_differential,
            "use_guidelines": True,
            "conservative_wording": True
        }
    }

    try:
        result = await generate_clinical_note(payload)
        result["warnings"].extend(extraction_warnings)
        return ClinicalNoteResponse(**result)
    except Exception as exc:
        logger.error(f"Note generation failed: {exc}")
        raise ExternalServiceError("OpenAI", str(exc))
