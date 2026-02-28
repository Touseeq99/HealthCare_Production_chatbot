"""
Differential Diagnosis Assistant — FastAPI Router
===================================================
Exposes the /api/ddx/generate endpoint (doctor/admin only).

Endpoint:  POST /api/ddx/generate
Auth:      Bearer token (doctor or admin role enforced)
Response:  Strict JSON per the DDx output schema
"""

from fastapi import APIRouter, Request, Depends, status, File, UploadFile, Form, HTTPException
from pydantic import BaseModel, Field, validator
from typing import Optional, List, Any
from utils.auth_dependencies import get_current_user
from utils.ddx_engine import generate_differential
from utils.error_handler import AppException, ExternalServiceError, AuthorizationError
from utils.logger import get_request_id
from utils.validation import SQLInjectionProtection, ValidationMiddleware
from slowapi import Limiter
from slowapi.util import get_remote_address
from config import settings
import logging
from utils.file_extractor import extract_text_from_upload, validate_upload

logger = logging.getLogger(__name__)
limiter = Limiter(key_func=get_remote_address)
router = APIRouter()


# ---------------------------------------------------------------------------
# Request / Response Pydantic models
# ---------------------------------------------------------------------------

class DdxOptions(BaseModel):
    """
    Behavioural flags.
    conservative_reasoning, use_guidelines, and include_red_flags are
    always enforced by the engine regardless of the values sent here.
    """
    include_ecg: bool = False
    include_labs: bool = False
    conservative_reasoning: bool = True   # Always ON — field kept for schema compat
    use_guidelines: bool = True           # Always ON — field kept for schema compat
    include_red_flags: bool = True        # Always ON — field kept for schema compat


class DdxRequest(BaseModel):
    """
    Input schema for POST /api/ddx/generate.

    Only case_summary is required; all other clinical data fields are
    optional but improve differential quality.
    """
    case_summary: str = Field(
        ...,
        min_length=5,
        max_length=2000,
        description="Age, sex, chief complaint, and duration (required)",
    )
    symptoms: Optional[str] = Field(
        default=None,
        max_length=3000,
        description="Additional symptom detail (optional)",
    )
    vitals: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="Vital signs (optional)",
    )
    lab_data: Optional[str] = Field(
        default=None,
        max_length=3000,
        description="Lab results — used only when options.include_labs=true",
    )
    ecg_data: Optional[str] = Field(
        default=None,
        max_length=3000,
        description="ECG interpretation — used only when options.include_ecg=true",
    )
    past_history: Optional[str] = Field(
        default=None,
        max_length=2000,
        description="Past medical / surgical history (optional)",
    )
    risk_factors: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="Relevant risk factors (optional)",
    )
    options: DdxOptions = Field(default_factory=DdxOptions)

    @validator("case_summary")
    def sanitize_case_summary(cls, v):
        return v.strip()

    @validator("symptoms", "vitals", "lab_data", "ecg_data", "past_history", "risk_factors")
    def sanitize_optional_fields(cls, v):
        if v:
            return v.strip()
        return v


class DdxDifferential(BaseModel):
    rank: int
    condition: str
    likelihood: str
    supporting_evidence: List[str]
    contradicting_evidence: List[str]
    guideline_note: Optional[str] = None


class DdxResponse(BaseModel):
    """Response schema — mirrors the DDx output specification exactly."""
    tool_label: str
    disclaimer: str
    differentials: List[DdxDifferential]
    red_flags: List[str]
    suggested_next_steps: List[str]
    uncertainty_statement: str
    warnings: List[str]


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.post(
    "/ddx/generate",
    response_model=DdxResponse,
    status_code=status.HTTP_200_OK,
    summary="Generate a structured differential diagnosis from clinical case data",
    description=(
        "Produces a ranked, multi-hypothesis differential with supporting and "
        "contradicting evidence, red flags, and suggested next diagnostic steps. "
        "Decision support only — does NOT provide definitive diagnoses or "
        "treatment recommendations. For physician use only."
    ),
    tags=["Differential Diagnosis"],
)
@limiter.limit(f"{settings.RATE_LIMIT * 2}/minute")
async def generate_ddx(
    request: Request,
    body: DdxRequest,
    current_user: Any = Depends(get_current_user),
):
    """
    Generate a differential diagnosis.

    - **Doctor or admin role required** — 403 returned for other roles.
    - Rate-limited to 2× global RATE_LIMIT per minute.
    - conservative_reasoning, use_guidelines, and include_red_flags are
      **always active** regardless of what is passed in options.
    """
    # ---- Role enforcement ------------------------------------------------
    user_role = getattr(current_user, "role", None)
    if user_role not in ("doctor", "admin"):
        raise AuthorizationError(
            "Access denied. Differential diagnosis generation is restricted "
            "to doctors and admins."
        )

    # ---- Request-level validation ----------------------------------------
    await ValidationMiddleware.validate_request_size(request, max_size_mb=1)
    await ValidationMiddleware.validate_content_type(request, ["application/json"])

    # SQL-injection guard on every free-text field
    free_text_fields = {
        "case_summary": body.case_summary,
        "symptoms": body.symptoms,
        "vitals": body.vitals,
        "lab_data": body.lab_data,
        "ecg_data": body.ecg_data,
        "past_history": body.past_history,
        "risk_factors": body.risk_factors,
    }
    for field_name, field_value in free_text_fields.items():
        if field_value:
            SQLInjectionProtection.validate_input_safety(field_value)

    # ---- Build engine payload --------------------------------------------
    payload = {
        "case_summary": body.case_summary,
        "symptoms": body.symptoms,
        "vitals": body.vitals,
        "lab_data": body.lab_data,
        "ecg_data": body.ecg_data,
        "past_history": body.past_history,
        "risk_factors": body.risk_factors,
        "options": body.options.dict(),
    }

    logger.info(
        "DDx request received",
        extra={
            "request_id": get_request_id(),
            "user_id": getattr(current_user, "id", "unknown"),
            "case_summary_len": len(body.case_summary),
            "include_ecg": body.options.include_ecg,
            "include_labs": body.options.include_labs,
        },
    )

    # ---- Call the engine -------------------------------------------------
    try:
        result = await generate_differential(payload)
    except Exception as exc:
        logger.error(
            f"Differential generation failed: {exc}",
            exc_info=True,
            extra={"request_id": get_request_id()},
        )
        raise ExternalServiceError("OpenAI", str(exc))

    return DdxResponse(**result)

@router.post(
    "/ddx/upload",
    response_model=DdxResponse,
    status_code=status.HTTP_200_OK,
    summary="Generate differential diagnosis from text and/or files (PDF/Image)",
    description=(
        "Standard multi-modal endpoint. You can provide a cases summary, ECG data, and "
        "Lab data as either raw text OR uploaded files. If a file is provided for a "
        "section, it takes precedence over the text for that section."
    ),
    tags=["Differential Diagnosis"],
)
@limiter.limit(f"{settings.RATE_LIMIT}/minute")
async def upload_ddx(
    request: Request,
    include_ecg: bool = Form(False),
    include_labs: bool = Form(False),
    case_summary: Optional[str] = Form(None),
    ecg_data: Optional[str] = Form(None),
    lab_data: Optional[str] = Form(None),
    clinical_file: Optional[UploadFile] = File(None),
    ecg_file: Optional[UploadFile] = File(None),
    lab_file: Optional[UploadFile] = File(None),
    current_user: Any = Depends(get_current_user),
):
    """
    Hybrid Differential Diagnosis endpoint (Text + Files).
    """
    user_role = getattr(current_user, "role", None)
    if user_role not in ("doctor", "admin"):
        raise AuthorizationError("Access denied.")

    final_case_summary = case_summary or ""
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
        final_case_summary = await process_file(clinical_file, "Case Summary")
    if ecg_file and ecg_file.filename:
        final_ecg_data = await process_file(ecg_file, "ECG Findings")
    if lab_file and lab_file.filename:
        final_lab_data = await process_file(lab_file, "Lab Results")

    if not final_case_summary.strip() and not final_ecg_data.strip() and not final_lab_data.strip():
        raise HTTPException(status_code=400, detail="No clinical data provided (neither text nor files).")

    payload = {
        "case_summary": final_case_summary,
        "ecg_data": final_ecg_data,
        "lab_data": final_lab_data,
        "options": {
            "include_ecg": include_ecg or bool(final_ecg_data),
            "include_labs": include_labs or bool(final_lab_data),
            "conservative_reasoning": True,
            "use_guidelines": True,
            "include_red_flags": True
        }
    }

    try:
        result = await generate_differential(payload)
        result["warnings"].extend(extraction_warnings)
        return DdxResponse(**result)
    except Exception as exc:
        logger.error(f"DDx generation failed: {exc}")
        raise ExternalServiceError("OpenAI", str(exc))
