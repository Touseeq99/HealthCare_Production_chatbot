"""
AI Clinical Note — FastAPI Router (Cardiology Edition)
=======================================================
Endpoints:
  POST /api/clinical-note/generate         — generate note / handover / discharge letter
  POST /api/clinical-note/save-patient     — save structured patient data for current user
  GET  /api/clinical-note/patients         — list saved patients for current user
  GET  /api/clinical-note/patients/{id}    — retrieve a single saved patient record
  POST /api/clinical-note/interpret-labs   — standalone blood-test interpretation
  POST /api/clinical-note/upload           — legacy multipart upload endpoint (kept for compat)

Auth:      Bearer token (doctor role enforced)
"""

from fastapi import APIRouter, Request, Depends, status, HTTPException, File, UploadFile, Form
from pydantic import BaseModel, Field, validator
from typing import Optional, List, Literal, Dict, Any
from utils.auth_dependencies import get_current_user
from utils.clinical_note_engine import generate_clinical_note, interpret_blood_tests
from utils.error_handler import AppException, ExternalServiceError, AuthorizationError
from utils.logger import get_request_id
from utils.validation import SQLInjectionProtection, ValidationMiddleware
from utils.supabase_client import get_supabase_client
from utils.file_extractor import extract_text_from_upload, validate_upload
from slowapi import Limiter
from slowapi.util import get_remote_address
from config import settings
import logging
import datetime

logger = logging.getLogger(__name__)
limiter = Limiter(key_func=get_remote_address)
router = APIRouter()


# ===========================================================================
# PYDANTIC MODELS — Structured Cardiology Patient Form
# ===========================================================================

class PatientIdentification(BaseModel):
    initials: str = Field(..., max_length=10, description="Patient initials only (e.g. 'J.D.')")
    mrn: Optional[str] = Field(None, max_length=50, description="Medical Record Number")
    dob: Optional[str] = Field(None, description="Date of Birth (YYYY-MM-DD)")
    age: Optional[int] = Field(None, ge=0, le=130)
    sex: Optional[Literal["Male", "Female", "Other", "Prefer not to say"]] = None
    location: Optional[str] = Field(None, max_length=100, description="Ward / clinic / hospital")
    date_of_admission: Optional[str] = Field(None, description="YYYY-MM-DD")
    date_of_discharge: Optional[str] = Field(None, description="YYYY-MM-DD")
    responsible_consultant: Optional[str] = Field(None, max_length=100)


class PresentingComplaint(BaseModel):
    complaints: Dict[str, bool] = Field(
        default_factory=lambda: {
            "chest_pain": False,
            "dyspnoea": False,
            "syncope": False,
            "palpitations": False,
            "heart_failure_symptoms": False,
            "stroke_embolic_event": False,
            "other": False,
        }
    )
    other_complaint: Optional[str] = Field(None, max_length=500)
    duration: Optional[str] = Field(None, max_length=200, description="Duration of symptoms")


class AssociatedSymptoms(BaseModel):
    nausea: bool = False
    diaphoresis: bool = False
    presyncope: bool = False
    orthopnoea: bool = False
    peripheral_oedema: bool = False


class RelevantMedicalHistory(BaseModel):
    coronary_artery_disease: bool = False
    atrial_fibrillation: bool = False
    heart_failure: bool = False
    hypertension: bool = False
    diabetes: bool = False
    hyperlipidaemia: bool = False
    stroke_tia: bool = False
    chronic_kidney_disease: bool = False
    obesity: bool = False
    sleep_apnoea: bool = False
    prior_cardiac_surgery: bool = False
    prior_pci: bool = False


class CardiovascularRiskFactors(BaseModel):
    smoking_history: bool = False
    family_history_premature_cvd: bool = False
    hypertension: bool = False
    diabetes: bool = False
    dyslipidaemia: bool = False
    sedentary_lifestyle: bool = False


class Vitals(BaseModel):
    heart_rate: Optional[str] = Field(None, max_length=50, description="e.g. '72 bpm'")
    blood_pressure: Optional[str] = Field(None, max_length=50, description="e.g. '120/80 mmHg'")
    oxygen_saturation: Optional[str] = Field(None, max_length=50, description="e.g. '98%'")
    temperature: Optional[str] = Field(None, max_length=50, description="e.g. '36.8°C'")


class ClinicalFindings(BaseModel):
    signs_of_heart_failure: bool = False
    murmur: bool = False
    peripheral_oedema: bool = False
    raised_jvp: bool = False
    lung_crepitations: bool = False


class ExaminationFindings(BaseModel):
    vitals: Vitals = Field(default_factory=Vitals)
    clinical_findings: ClinicalFindings = Field(default_factory=ClinicalFindings)


class ECGData(BaseModel):
    rhythm: Optional[str] = Field(None, max_length=200)
    heart_rate: Optional[str] = Field(None, max_length=100)
    conduction_abnormalities: Optional[str] = Field(None, max_length=300)
    st_t_changes: Optional[str] = Field(None, max_length=300)
    qt_interval: Optional[str] = Field(None, max_length=100)
    image_uploaded: bool = False
    ecg_image_path: Optional[str] = Field(None, description="Supabase storage path to uploaded ECG image")


class Echocardiography(BaseModel):
    lvef: Optional[str] = Field(None, max_length=20, description="Left ventricular ejection fraction (%)")
    lv_size: Optional[str] = Field(None, max_length=100)
    rv_function: Optional[str] = Field(None, max_length=100)
    lv_dilation: Optional[Literal["Yes", "No", "Not assessed"]] = None
    rwma: Optional[Literal["Yes", "No", "Not assessed"]] = Field(None, description="Regional wall motion abnormality")
    significant_valve_disease: Optional[Literal["Yes", "No", "Not assessed"]] = None
    valvular_disease: Optional[str] = Field(None, max_length=300)


class CardiacImaging(BaseModel):
    echocardiography: Echocardiography = Field(default_factory=Echocardiography)


class LaboratoryTests(BaseModel):
    troponin: Optional[str] = Field(None, max_length=100)
    bnp_nt_probnp: Optional[str] = Field(None, max_length=100)
    creatinine: Optional[str] = Field(None, max_length=100)
    egfr: Optional[str] = Field(None, max_length=100)
    haemoglobin: Optional[str] = Field(None, max_length=100)
    electrolytes: Optional[str] = Field(None, max_length=200)
    crp: Optional[str] = Field(None, max_length=100)
    d_dimer: Optional[str] = Field(None, max_length=100)


class OtherInvestigations(BaseModel):
    ct_coronary_angiography: bool = False
    invasive_coronary_angiography: bool = False
    cardiac_mri: bool = False


class KeyInvestigations(BaseModel):
    laboratory_tests: LaboratoryTests = Field(default_factory=LaboratoryTests)
    other_investigations: OtherInvestigations = Field(default_factory=OtherInvestigations)


class TreatmentDuringAdmission(BaseModel):
    pci: bool = False
    antiarrhythmic_therapy: bool = False
    diuretics: bool = False
    anticoagulation: bool = False
    cardioversion: bool = False
    ablation: bool = False


class Medication(BaseModel):
    name: str = Field(..., max_length=100)
    dose: Optional[str] = Field(None, max_length=100)
    frequency: Optional[str] = Field(None, max_length=100)


class ClinicalCourse(BaseModel):
    hospital_course_summary: Optional[str] = Field(None, max_length=2000)
    complications: Optional[str] = Field(None, max_length=1000)


class DischargePlan(BaseModel):
    follow_up_clinic: bool = False
    cardiology_review: bool = False
    gp_follow_up: bool = False
    repeat_investigations: bool = False


class LifestyleAdvice(BaseModel):
    smoking_cessation: bool = False
    exercise: bool = False
    diet: bool = False
    weight_management: bool = False
    alcohol_reduction: bool = False


class PatientClinicalData(BaseModel):
    """
    Full structured cardiology patient dataset.
    All sub-models are optional to allow partial saves / progressive form filling.
    """
    patient_identification: PatientIdentification
    presenting_complaint: PresentingComplaint = Field(default_factory=PresentingComplaint)
    associated_symptoms: AssociatedSymptoms = Field(default_factory=AssociatedSymptoms)
    relevant_medical_history: RelevantMedicalHistory = Field(default_factory=RelevantMedicalHistory)
    cardiovascular_risk_factors: CardiovascularRiskFactors = Field(default_factory=CardiovascularRiskFactors)
    examination_findings: ExaminationFindings = Field(default_factory=ExaminationFindings)
    ecg: ECGData = Field(default_factory=ECGData)
    cardiac_imaging: CardiacImaging = Field(default_factory=CardiacImaging)
    key_investigations: KeyInvestigations = Field(default_factory=KeyInvestigations)
    primary_diagnosis: Optional[str] = Field(None, max_length=500)
    treatment_during_admission: TreatmentDuringAdmission = Field(default_factory=TreatmentDuringAdmission)
    medication_list_at_discharge: List[Medication] = Field(default_factory=list)
    clinical_course: ClinicalCourse = Field(default_factory=ClinicalCourse)
    discharge_plan: DischargePlan = Field(default_factory=DischargePlan)
    lifestyle_advice: LifestyleAdvice = Field(default_factory=LifestyleAdvice)
    additional_clinical_notes: Optional[str] = Field(None, max_length=3000)


# ---------------------------------------------------------------------------
# Generate Request / Response
# ---------------------------------------------------------------------------

class GenerateNoteRequest(BaseModel):
    output_type: Literal["CLINICAL_NOTE", "HANDOVER_NOTE", "DISCHARGE_LETTER"] = Field(
        default="CLINICAL_NOTE",
        description="Which document to generate"
    )
    patient_data: PatientClinicalData
    # optional: if a record_id is supplied, reload and update that patient
    record_id: Optional[str] = None


class ClinicalNoteResponse(BaseModel):
    output_type: str
    note_type: str
    generated_note: str
    sections: dict
    warnings: List[str]
    disclaimer: str


# ---------------------------------------------------------------------------
# Save / List Patient Models
# ---------------------------------------------------------------------------

class SavePatientRequest(BaseModel):
    patient_data: PatientClinicalData
    record_id: Optional[str] = Field(None, description="If set, update existing record")


class SavePatientResponse(BaseModel):
    record_id: str
    file_path: str
    message: str


class PatientListItem(BaseModel):
    record_id: str
    initials: str
    mrn: Optional[str]
    date_of_admission: Optional[str]
    created_at: str
    updated_at: str
    file_path: str


# ---------------------------------------------------------------------------
# Blood Test Interpretation Models
# ---------------------------------------------------------------------------

class BloodTestRequest(BaseModel):
    egfr: Optional[float] = Field(None, ge=0)
    egfr_unit: Optional[str] = "mL/min/1.73m²"
    troponin: Optional[float] = Field(None, ge=0)
    troponin_unit: Optional[str] = None
    troponin_url: Optional[str] = Field(None, description="Upper reference limit")
    crp: Optional[float] = Field(None, ge=0)
    crp_unit: Optional[str] = "mg/L"
    d_dimer: Optional[float] = Field(None, ge=0)
    d_dimer_unit: Optional[str] = "mg/L FEU"
    patient_age: Optional[int] = Field(None, ge=0, le=130)


# ===========================================================================
# HELPER: build Supabase storage path
# ===========================================================================

def _build_storage_path(username: str, initials: str, date_str: Optional[str]) -> str:
    """
    Pattern: <username>/<date>_<initials>.json
    e.g.  dr.smith/2026-03-15_JD.json
    """
    date_part = date_str or datetime.date.today().isoformat()
    safe_initials = initials.replace(".", "").replace(" ", "").upper()
    safe_username = username.replace(" ", "_").lower()
    return f"{safe_username}/{date_part}_{safe_initials}.json"


# ===========================================================================
# ENDPOINTS
# ===========================================================================

# ---------------------------------------------------------------------------
# 1. GENERATE NOTE / HANDOVER / DISCHARGE LETTER
# ---------------------------------------------------------------------------

@router.post(
    "/clinical-note/generate",
    response_model=ClinicalNoteResponse,
    status_code=status.HTTP_200_OK,
    summary="Generate a clinical note, handover note, or discharge letter from a structured patient dataset",
    tags=["Clinical Notes"],
)
@limiter.limit(f"{settings.RATE_LIMIT * 2}/minute")
async def generate_note(
    request: Request,
    body: GenerateNoteRequest,
    current_user: Any = Depends(get_current_user),
):
    """
    Accepts a fully structured cardiology patient form and generates:
    - **CLINICAL_NOTE** — full cardiology clinical note
    - **HANDOVER_NOTE** — concise handover for incoming team
    - **DISCHARGE_LETTER** — formal GP discharge correspondence

    Doctor/admin role required.
    """
    user_role = getattr(current_user, "role", None)
    if user_role not in ("doctor", "admin"):
        raise AuthorizationError(
            "Access denied. Clinical note generation is restricted to doctors and admins."
        )

    await ValidationMiddleware.validate_request_size(request, max_size_mb=2)

    # Free-text SQL injection guard on narrative fields
    if body.patient_data.additional_clinical_notes:
        SQLInjectionProtection.validate_input_safety(body.patient_data.additional_clinical_notes)
    if body.patient_data.clinical_course.hospital_course_summary:
        SQLInjectionProtection.validate_input_safety(body.patient_data.clinical_course.hospital_course_summary)

    payload = {
        "output_type": body.output_type,
        "patient_data": body.patient_data.dict(),
    }

    logger.info(
        "Clinical document request received",
        extra={
            "request_id": get_request_id(),
            "output_type": body.output_type,
            "user_id": getattr(current_user, "id", "unknown"),
            "patient_initials": body.patient_data.patient_identification.initials,
        },
    )

    try:
        result = await generate_clinical_note(payload)
    except Exception as exc:
        logger.error(f"Clinical note generation failed: {exc}", exc_info=True)
        raise ExternalServiceError("OpenAI", str(exc))

    return ClinicalNoteResponse(**result)


# ---------------------------------------------------------------------------
# 2. SAVE PATIENT RECORD
# ---------------------------------------------------------------------------

@router.post(
    "/clinical-note/save-patient",
    response_model=SavePatientResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Save or update a patient's structured clinical data",
    tags=["Clinical Notes"],
)
@limiter.limit(f"{settings.RATE_LIMIT * 2}/minute")
async def save_patient(
    request: Request,
    body: SavePatientRequest,
    current_user: Any = Depends(get_current_user),
):
    """
    Persists the structured patient form to the `patient_clinical_notes` table.
    File path pattern: <username>/<date>_<initials> for easy identification.

    - If `record_id` is supplied in the body, the existing record is updated (upsert).
    - Returns the record ID and file path for frontend reference.
    """
    user_role = getattr(current_user, "role", None)
    if user_role not in ("doctor", "admin"):
        raise AuthorizationError("Access denied.")

    supabase = get_supabase_client()
    user_id = str(getattr(current_user, "id", ""))
    username = getattr(current_user, "name", "") or getattr(current_user, "email", user_id)

    pid = body.patient_data.patient_identification
    file_path = _build_storage_path(
        username=username,
        initials=pid.initials,
        date_str=pid.date_of_admission,
    )

    now_iso = datetime.datetime.utcnow().isoformat()
    record = {
        "user_id": user_id,
        "file_path": file_path,
        "patient_initials": pid.initials,
        "patient_mrn": pid.mrn,
        "date_of_admission": pid.date_of_admission,
        "patient_data": body.patient_data.dict(),
        "updated_at": now_iso,
    }

    try:
        if body.record_id:
            # Update existing record
            resp = (
                supabase.table("patient_clinical_notes")
                .update(record)
                .eq("id", body.record_id)
                .eq("user_id", user_id)  # ownership check
                .execute()
            )
            if not resp.data:
                raise HTTPException(status_code=404, detail="Record not found or access denied.")
            saved_id = body.record_id
        else:
            # Insert new record
            record["created_at"] = now_iso
            resp = supabase.table("patient_clinical_notes").insert(record).execute()
            if not resp.data:
                raise HTTPException(status_code=500, detail="Failed to save patient record.")
            saved_id = str(resp.data[0]["id"])

        logger.info(
            "Patient clinical data saved",
            extra={
                "user_id": user_id,
                "record_id": saved_id,
                "file_path": file_path,
            },
        )

        return SavePatientResponse(
            record_id=saved_id,
            file_path=file_path,
            message="Patient record saved successfully.",
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Failed to save patient: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Database error: {str(exc)}")


# ---------------------------------------------------------------------------
# 3. LIST PATIENTS
# ---------------------------------------------------------------------------

@router.get(
    "/clinical-note/patients",
    status_code=status.HTTP_200_OK,
    summary="List all saved patients for the currently logged-in doctor",
    tags=["Clinical Notes"],
)
@limiter.limit(f"{settings.RATE_LIMIT * 3}/minute")
async def list_patients(
    request: Request,
    current_user: Any = Depends(get_current_user),
):
    """
    Returns a list of all saved patient records belonging to the current user.
    Includes initials, MRN, admission date, record ID, and file path.
    """
    user_role = getattr(current_user, "role", None)
    if user_role not in ("doctor", "admin"):
        raise AuthorizationError("Access denied.")

    supabase = get_supabase_client()
    user_id = str(getattr(current_user, "id", ""))

    try:
        resp = (
            supabase.table("patient_clinical_notes")
            .select("id, patient_initials, patient_mrn, date_of_admission, created_at, updated_at, file_path")
            .eq("user_id", user_id)
            .order("updated_at", desc=True)
            .execute()
        )
        return {"patients": resp.data or []}
    except Exception as exc:
        logger.error(f"Failed to list patients: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve patient list.")


# ---------------------------------------------------------------------------
# 4. GET SINGLE PATIENT
# ---------------------------------------------------------------------------

@router.get(
    "/clinical-note/patients/{record_id}",
    status_code=status.HTTP_200_OK,
    summary="Retrieve a single saved patient record",
    tags=["Clinical Notes"],
)
@limiter.limit(f"{settings.RATE_LIMIT * 3}/minute")
async def get_patient(
    request: Request,
    record_id: str,
    current_user: Any = Depends(get_current_user),
):
    """
    Fetches the full patient_data JSON for a given record.
    Only the owning doctor (or admin) can access.
    """
    user_role = getattr(current_user, "role", None)
    if user_role not in ("doctor", "admin"):
        raise AuthorizationError("Access denied.")

    supabase = get_supabase_client()
    user_id = str(getattr(current_user, "id", ""))

    try:
        resp = (
            supabase.table("patient_clinical_notes")
            .select("*")
            .eq("id", record_id)
            .eq("user_id", user_id)
            .single()
            .execute()
        )
        if not resp.data:
            raise HTTPException(status_code=404, detail="Patient record not found.")
        return resp.data
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Failed to retrieve patient {record_id}: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve patient record.")


# ---------------------------------------------------------------------------
# 5. BLOOD TEST INTERPRETATION
# ---------------------------------------------------------------------------

@router.post(
    "/clinical-note/interpret-labs",
    status_code=status.HTTP_200_OK,
    summary="Interpret blood test results (eGFR, Troponin, CRP, D-Dimer)",
    tags=["Clinical Notes"],
)
@limiter.limit(f"{settings.RATE_LIMIT * 2}/minute")
async def interpret_labs(
    request: Request,
    body: BloodTestRequest,
    current_user: Any = Depends(get_current_user),
):
    """
    Standalone blood test interpreter for:
    - **eGFR** (CKD staging)
    - **Troponin** (myocardial injury assessment)
    - **CRP** (inflammatory marker)
    - **D-Dimer** (VTE risk stratification with age-adjusted cutoff)
    """
    user_role = getattr(current_user, "role", None)
    if user_role not in ("doctor", "admin"):
        raise AuthorizationError("Access denied.")

    lab_data = body.dict(exclude_none=True)
    if not any(v is not None for v in [body.egfr, body.troponin, body.crp, body.d_dimer]):
        raise HTTPException(status_code=400, detail="At least one lab value must be provided.")

    try:
        result = await interpret_blood_tests(lab_data)
        return result
    except Exception as exc:
        logger.error(f"Blood test interpretation failed: {exc}", exc_info=True)
        raise ExternalServiceError("OpenAI", str(exc))


# ---------------------------------------------------------------------------
# 6. LEGACY UPLOAD ENDPOINT (backward compatibility)
# ---------------------------------------------------------------------------

@router.post(
    "/clinical-note/upload",
    response_model=ClinicalNoteResponse,
    status_code=status.HTTP_200_OK,
    summary="[Legacy] Generate clinical note from text and/or files (PDF/Image)",
    description="Legacy multipart upload endpoint kept for backwards compatibility.",
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

    if clinical_file and clinical_file.filename:
        final_raw_input = await process_file(clinical_file, "Clinical History")
    if ecg_file and ecg_file.filename:
        final_ecg_data = await process_file(ecg_file, "ECG Findings")
    if lab_file and lab_file.filename:
        final_lab_data = await process_file(lab_file, "Lab Results")

    if not final_raw_input.strip() and not final_ecg_data.strip() and not final_lab_data.strip():
        raise HTTPException(status_code=400, detail="No clinical data provided (neither text nor files).")

    payload = {
        "output_type": "CLINICAL_NOTE",
        "raw_input": final_raw_input,
        "ecg_data": final_ecg_data,
        "lab_data": final_lab_data,
        "options": {
            "include_ecg": include_ecg or bool(final_ecg_data),
            "include_labs": include_labs or bool(final_lab_data),
            "include_differential": include_differential,
            "use_guidelines": True,
            "conservative_wording": True,
        },
    }

    try:
        result = await generate_clinical_note(payload)
        result.setdefault("warnings", []).extend(extraction_warnings)
        return ClinicalNoteResponse(**result)
    except Exception as exc:
        logger.error(f"Note generation failed: {exc}")
        raise ExternalServiceError("OpenAI", str(exc))
