"""
AI Clinical Note Engine — Cardiology Edition
=============================================
Generates structured clinical documents (Clinical Note, Handover Note,
Discharge Letter) from a rich, structured cardiology patient dataset.

Also provides standalone blood-test interpretation helpers.
"""

import json
import logging
import time
from openai import AsyncOpenAI
from dotenv import load_dotenv
from typing import Optional

load_dotenv()

client = AsyncOpenAI()
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared safety rules injected into every prompt
# ---------------------------------------------------------------------------
_SAFETY_RULES = """
## ABSOLUTE RULES (NEVER BREAK)
- NEVER fabricate clinical data, lab values, or findings not present in the input.
- NEVER output a definitive diagnosis without hedge language ("consistent with", "suggestive of", "may represent", "cannot exclude").
- NEVER include patient full name — use initials only.
- ALWAYS use conservative/hedged language.
- NEVER make statements implying negligence or legal liability.
- NEVER use percentage numbers (e.g., "85%") for likelihood.
- ALWAYS include the disclaimer field in every response.
- Return ONLY valid JSON — no backticks, no markdown, no preamble.

## FORMATTING & STYLE RULES
- Use **bold** for critical findings, abnormal values, primary diagnoses.
- Use bullet points for lists (history, symptoms, medications, exam findings, plans).
- Use clear SECTION HEADERS in ALL CAPS followed by a newline.
- Separate major sections with a double newline.
- Maintain formal, medical reporting style with high scanability.
"""

# ---------------------------------------------------------------------------
# SYSTEM PROMPTS — one per output type
# ---------------------------------------------------------------------------

CLINICAL_NOTE_SYSTEM_PROMPT = f"""
You are a clinical documentation AI called "AI Clinical Note," embedded in a cardiology doctor-assist tool.
Your ONLY job is to transform a structured cardiology patient dataset into a professional, legally-safe clinical note.
{_SAFETY_RULES}

## CARDIOLOGY CLINICAL NOTE SECTIONS
PATIENT IDENTIFICATION | PRESENTING COMPLAINT | HISTORY OF PRESENTING COMPLAINT |
RELEVANT MEDICAL HISTORY | CARDIOVASCULAR RISK FACTORS | EXAMINATION FINDINGS |
ECG FINDINGS | CARDIAC IMAGING | KEY INVESTIGATIONS | LAB INTERPRETATION |
DIAGNOSIS | TREATMENT DURING ADMISSION | MEDICATION LIST | CLINICAL COURSE |
DISCHARGE PLAN | LIFESTYLE ADVICE | ADDITIONAL NOTES

## BLOOD TEST INTERPRETATION RULES
When lab values are provided, interpret them using these thresholds:
- eGFR: ≥90 Normal | 60-89 Mild CKD | 30-59 Moderate CKD | 15-29 Severe CKD | <15 Kidney Failure
- Troponin: Flag as **[ELEVATED]** if above reference range; indicate High Sensitivity if applicable
- CRP: <10 mg/L Normal | 10-100 Slightly-moderately elevated | >100 Markedly elevated
- D-Dimer: Flag as **[ELEVATED]** if above age-adjusted cutoff; note PE/DVT risk relevance

## OUTPUT FORMAT (strict JSON)
{{
  "output_type": "CLINICAL_NOTE",
  "note_type": "<subtype if SOAP/OPD/etc, else CARDIOLOGY>",
  "generated_note": "<full structured note>",
  "sections": {{ "<SECTION_NAME>": "<section content>" }},
  "warnings": ["<missing data flags, empty array if none>"],
  "disclaimer": "This note was AI-generated and must be reviewed and approved by the treating physician before clinical or legal use."
}}
"""

HANDOVER_NOTE_SYSTEM_PROMPT = f"""
You are a clinical documentation AI called "AI Clinical Note," embedded in a cardiology doctor-assist tool.
Your ONLY job is to transform a structured cardiology patient dataset into a concise, actionable HANDOVER NOTE for an incoming clinical team.
{_SAFETY_RULES}

## HANDOVER NOTE STRUCTURE
PATIENT SUMMARY | ACTIVE ISSUES | RECENT CHANGES | OUTSTANDING TASKS | OVERNIGHT CONCERNS | ESCALATION CRITERIA

## HANDOVER NOTE STYLE RULES
- Be concise — each section should be scannable in under 30 seconds.
- Use SBAR framework where applicable (Situation, Background, Assessment, Recommendation).
- Flag critical abnormals with **[ALERT]** tag.
- Outstanding tasks must use checkbox format: "☐ Task description"

## OUTPUT FORMAT (strict JSON)
{{
  "output_type": "HANDOVER_NOTE",
  "generated_note": "<full handover note>",
  "sections": {{ "<SECTION_NAME>": "<section content>" }},
  "warnings": ["<missing data flags>"],
  "disclaimer": "This note was AI-generated and must be reviewed and approved by the treating physician before clinical or legal use."
}}
"""

DISCHARGE_LETTER_SYSTEM_PROMPT = f"""
You are a clinical documentation AI called "AI Clinical Note," embedded in a cardiology doctor-assist tool.
Your ONLY job is to transform a structured cardiology patient dataset into a formal DISCHARGE LETTER addressed from the responsible consultant to the patient's GP/primary care physician.
{_SAFETY_RULES}

## DISCHARGE LETTER STRUCTURE
PATIENT DETAILS | ADMISSION SUMMARY | CLINICAL FINDINGS | INVESTIGATIONS | 
DIAGNOSIS | TREATMENT | DISCHARGE MEDICATIONS | FOLLOW-UP PLAN | URGENT SAFETY NET | 
LIFESTYLE ADVICE | CLOSING REMARKS

## DISCHARGE LETTER STYLE RULES
- Address: "Dear Dr [GP name if known, else 'Colleague'],"
- Tone: Formal medical correspondence — third-person ("The patient was admitted...").
- Lead with admission/discharge dates and primary diagnosis.
- Medication table format: Name | Dose | Frequency | Duration.
- End with responsible consultant name and contact.

## OUTPUT FORMAT (strict JSON)
{{
  "output_type": "DISCHARGE_LETTER",
  "generated_note": "<full discharge letter>",
  "sections": {{ "<SECTION_NAME>": "<section content>" }},
  "warnings": ["<missing data flags>"],
  "disclaimer": "This letter was AI-generated and must be reviewed and approved by the treating physician before clinical or legal use."
}}
"""

# ---------------------------------------------------------------------------
# Blood-test standalone interpretation prompt
# ---------------------------------------------------------------------------
BLOOD_TEST_SYSTEM_PROMPT = """
You are a clinical laboratory interpretation AI. Interpret blood test results using evidence-based thresholds.
Return ONLY valid JSON.

Interpret the following tests if provided (skip any not present):

eGFR (mL/min/1.73m²):
  ≥90 → Stage G1 Normal or High
  60–89 → Stage G2 Mildly decreased
  45–59 → Stage G3a Mildly-moderately decreased
  30–44 → Stage G3b Moderately-severely decreased
  15–29 → Stage G4 Severely decreased
  <15  → Stage G5 Kidney Failure

Troponin I/T (high-sensitivity):
  Below URL → Normal, ACS unlikely
  1–2× URL → Borderline — serial measurement recommended
  >2× URL → Elevated — consistent with myocardial injury
  (URL = upper reference limit; flag if not provided)

CRP (mg/L):
  <5 → Normal
  5–10 → Borderline
  10–100 → Elevated — bacterial infection/inflammation likely
  >100 → Markedly elevated — serious bacterial infection/sepsis possible

D-Dimer (mg/L FEU or μg/mL):
  Below age-adjusted cutoff → VTE unlikely
  Age-adjusted cutoff = (age × 0.01) μg/mL for age >50
  Above cutoff → Further imaging recommended to exclude PE/DVT

OUTPUT FORMAT (strict JSON):
{
  "interpretations": {
    "eGFR": { "value": null, "unit": "", "stage": "", "interpretation": "", "flag": "" },
    "troponin": { "value": null, "unit": "", "interpretation": "", "flag": "" },
    "CRP": { "value": null, "unit": "", "interpretation": "", "flag": "" },
    "d_dimer": { "value": null, "unit": "", "interpretation": "", "flag": "" }
  },
  "overall_summary": "",
  "warnings": []
}
"""


# ---------------------------------------------------------------------------
# Helper — flatten structured patient data into a readable user message
# ---------------------------------------------------------------------------

def _build_cardiology_message(patient_data: dict, output_type: str) -> str:
    """Convert the structured patient JSON into a readable prompt string."""
    lines = [f"OUTPUT TYPE REQUESTED: {output_type}", ""]

    def _v(val, default="N/A"):
        """Null-safe string converter."""
        if val is None:
            return str(default)
        return str(val)

    # --- Patient Identification ---
    pid = patient_data.get("patient_identification", {})
    lines.append("=== PATIENT IDENTIFICATION ===")
    lines.append(f"Initials: {_v(pid.get('initials'))}")
    lines.append(f"MRN: {_v(pid.get('mrn'))}")
    lines.append(f"DOB: {_v(pid.get('dob'))}")
    lines.append(f"Age: {_v(pid.get('age'))}")
    lines.append(f"Sex: {_v(pid.get('sex'))}")
    lines.append(f"Location: {_v(pid.get('location'))}")
    lines.append(f"Date of Admission: {_v(pid.get('date_of_admission'))}")
    lines.append(f"Date of Discharge: {_v(pid.get('date_of_discharge'))}")
    lines.append(f"Responsible Consultant: {_v(pid.get('responsible_consultant'))}")
    lines.append("")

    # --- Presenting Complaint ---
    pc = patient_data.get("presenting_complaint", {})
    lines.append("=== PRESENTING COMPLAINT ===")
    selected_pc = [k for k, v in pc.get("complaints", {}).items() if v]
    lines.append(f"Selected: {', '.join(selected_pc) if selected_pc else 'None specified'}")
    lines.append(f"Other: {_v(pc.get('other_complaint'), '')}")
    lines.append(f"Duration of symptoms: {_v(pc.get('duration'))}")
    lines.append("")

    # --- Key Associated Symptoms ---
    assoc = patient_data.get("associated_symptoms", {})
    lines.append("=== KEY ASSOCIATED SYMPTOMS ===")
    selected_symp = [k for k, v in assoc.items() if v]
    lines.append(f"{', '.join(selected_symp) if selected_symp else 'None reported'}")
    lines.append("")

    # --- Relevant Medical History ---
    rmh = patient_data.get("relevant_medical_history", {})
    lines.append("=== RELEVANT MEDICAL HISTORY ===")
    selected_rmh = [k for k, v in rmh.items() if v]
    lines.append(f"{', '.join(selected_rmh) if selected_rmh else 'None reported'}")
    lines.append("")

    # --- Cardiovascular Risk Factors ---
    crf = patient_data.get("cardiovascular_risk_factors", {})
    lines.append("=== CARDIOVASCULAR RISK FACTORS ===")
    selected_crf = [k for k, v in crf.items() if v]
    lines.append(f"{', '.join(selected_crf) if selected_crf else 'None reported'}")
    lines.append("")

    # --- Examination Findings ---
    exam = patient_data.get("examination_findings", {})
    vitals = exam.get("vitals", {})
    clinical = exam.get("clinical_findings", {})
    lines.append("=== EXAMINATION FINDINGS ===")
    lines.append("Vitals:")
    lines.append(f"  Heart Rate: {_v(vitals.get('heart_rate'))}")
    lines.append(f"  Blood Pressure: {_v(vitals.get('blood_pressure'))}")
    lines.append(f"  O2 Saturation: {_v(vitals.get('oxygen_saturation'))}")
    lines.append(f"  Temperature: {_v(vitals.get('temperature'))}")
    lines.append("Clinical Findings:")
    selected_cf = [k for k, v in clinical.items() if v]
    lines.append(f"  {', '.join(selected_cf) if selected_cf else 'None documented'}")
    lines.append("")

    # --- ECG ---
    ecg = patient_data.get("ecg", {})
    lines.append("=== ECG ===")
    lines.append(f"Rhythm: {_v(ecg.get('rhythm'))}")
    lines.append(f"Heart Rate: {_v(ecg.get('heart_rate'))}")
    lines.append(f"Conduction Abnormalities: {_v(ecg.get('conduction_abnormalities'))}")
    lines.append(f"ST/T Changes: {_v(ecg.get('st_t_changes'))}")
    lines.append(f"QT Interval: {_v(ecg.get('qt_interval'))}")
    lines.append(f"ECG Image Uploaded: {'Yes' if ecg.get('image_uploaded') else 'No'}")
    lines.append("")

    # --- Cardiac Imaging ---
    imaging = patient_data.get("cardiac_imaging", {})
    echo = imaging.get("echocardiography", {})
    lines.append("=== CARDIAC IMAGING (Echocardiography) ===")
    lines.append(f"LVEF: {_v(echo.get('lvef'))}%")
    lines.append(f"LV Size: {_v(echo.get('lv_size'))}")
    lines.append(f"RV Function: {_v(echo.get('rv_function'))}")
    lines.append(f"LV Dilation: {_v(echo.get('lv_dilation'))}")
    lines.append(f"Regional Wall Motion Abnormality: {_v(echo.get('rwma'))}")
    lines.append(f"Significant Valve Disease: {_v(echo.get('significant_valve_disease'))}")
    lines.append(f"Valvular Disease Detail: {_v(echo.get('valvular_disease'))}")
    lines.append("")

    # --- Key Investigations ---
    inv = patient_data.get("key_investigations", {})
    labs = inv.get("laboratory_tests", {})
    other_inv = inv.get("other_investigations", {})
    lines.append("=== KEY INVESTIGATIONS ===")
    lines.append("Laboratory Tests:")
    lines.append(f"  Troponin: {_v(labs.get('troponin'))}")
    lines.append(f"  BNP/NT-proBNP: {_v(labs.get('bnp_nt_probnp'))}")
    lines.append(f"  Creatinine: {_v(labs.get('creatinine'))}")
    lines.append(f"  eGFR: {_v(labs.get('egfr'))}")
    lines.append(f"  Haemoglobin: {_v(labs.get('haemoglobin'))}")
    lines.append(f"  Electrolytes: {_v(labs.get('electrolytes'))}")
    lines.append(f"  CRP: {_v(labs.get('crp'))}")
    lines.append(f"  D-Dimer: {_v(labs.get('d_dimer'))}")
    lines.append("Other Investigations:")
    selected_oi = [k for k, v in other_inv.items() if v]
    lines.append(f"  {', '.join(selected_oi) if selected_oi else 'None'}")
    lines.append("")

    # --- Diagnosis ---
    lines.append("=== DIAGNOSIS ===")
    lines.append(f"Primary Diagnosis: {_v(patient_data.get('primary_diagnosis'))}")
    lines.append("")

    # --- Treatment ---
    treatment = patient_data.get("treatment_during_admission", {})
    selected_tx = [k for k, v in treatment.items() if v]
    lines.append("=== TREATMENT DURING ADMISSION ===")
    lines.append(f"{', '.join(selected_tx) if selected_tx else 'None documented'}")
    lines.append("")

    # --- Medications ---
    meds = patient_data.get("medication_list_at_discharge", [])
    lines.append("=== MEDICATION LIST AT DISCHARGE ===")
    if meds:
        for med in meds:
            name = _v(med.get("name"), "Unknown")
            dose = _v(med.get("dose"), "")
            freq = _v(med.get("frequency"), "")
            lines.append(f"  - {name}: {dose} {freq}")
    else:
        lines.append("  None documented")
    lines.append("")

    # --- Clinical Course ---
    course = patient_data.get("clinical_course", {})
    lines.append("=== CLINICAL COURSE ===")
    lines.append(f"Hospital Course: {_v(course.get('hospital_course_summary'))}")
    lines.append(f"Complications: {_v(course.get('complications'))}")
    lines.append("")

    # --- Discharge Plan ---
    discharge = patient_data.get("discharge_plan", {})
    selected_dp = [k for k, v in discharge.items() if v]
    lines.append("=== DISCHARGE PLAN ===")
    lines.append(f"{', '.join(selected_dp) if selected_dp else 'None documented'}")
    lines.append("")

    # --- Lifestyle Advice ---
    lifestyle = patient_data.get("lifestyle_advice", {})
    selected_la = [k for k, v in lifestyle.items() if v]
    lines.append("=== LIFESTYLE ADVICE ===")
    lines.append(f"{', '.join(selected_la) if selected_la else 'None documented'}")
    lines.append("")

    # --- Additional Notes ---
    lines.append("=== ADDITIONAL CLINICAL NOTES ===")
    lines.append(_v(patient_data.get("additional_clinical_notes"), "None"))
    lines.append("")

    lines.append("Generate the document now. Return valid JSON only.")
    return "\n".join(lines)


def _build_blood_test_message(lab_data: dict) -> str:
    """Build user message for blood test interpretation."""
    parts = ["Interpret the following blood test results:\n"]
    if lab_data.get("egfr") is not None:
        parts.append(f"eGFR: {lab_data['egfr']} {lab_data.get('egfr_unit', 'mL/min/1.73m²')}")
    if lab_data.get("troponin") is not None:
        parts.append(f"Troponin: {lab_data['troponin']} {lab_data.get('troponin_unit', '')} (URL: {lab_data.get('troponin_url', 'not provided')})")
    if lab_data.get("crp") is not None:
        parts.append(f"CRP: {lab_data['crp']} {lab_data.get('crp_unit', 'mg/L')}")
    if lab_data.get("d_dimer") is not None:
        age = lab_data.get("patient_age")
        age_str = f" | Patient age: {age}" if age else ""
        parts.append(f"D-Dimer: {lab_data['d_dimer']} {lab_data.get('d_dimer_unit', 'mg/L FEU')}{age_str}")
    if len(parts) == 1:
        parts.append("No lab values provided.")
    parts.append("\nReturn valid JSON only.")
    return "\n".join(parts)


def _select_system_prompt(output_type: str) -> str:
    mapping = {
        "CLINICAL_NOTE": CLINICAL_NOTE_SYSTEM_PROMPT,
        "HANDOVER_NOTE": HANDOVER_NOTE_SYSTEM_PROMPT,
        "DISCHARGE_LETTER": DISCHARGE_LETTER_SYSTEM_PROMPT,
    }
    return mapping.get(output_type.upper(), CLINICAL_NOTE_SYSTEM_PROMPT)


# ---------------------------------------------------------------------------
# Main entry points
# ---------------------------------------------------------------------------

async def generate_clinical_note(payload: dict) -> dict:
    """
    Generate a clinical document from a structured cardiology patient payload.

    payload keys
    ------------
    output_type     : "CLINICAL_NOTE" | "HANDOVER_NOTE" | "DISCHARGE_LETTER"
    patient_data    : dict — full structured patient form
    """
    start = time.time()

    output_type = payload.get("output_type", "CLINICAL_NOTE").upper()
    patient_data = payload.get("patient_data", {})

    # Legacy plain-text path (backward compat with old raw_input based calls)
    raw_input = payload.get("raw_input", "")
    ecg_data = payload.get("ecg_data")
    lab_data = payload.get("lab_data")
    options = payload.get("options", {})

    if patient_data:
        user_message = _build_cardiology_message(patient_data, output_type)
    else:
        # Fallback: old-style plain text request
        parts = [f"OUTPUT TYPE: {output_type}", f"\nRAW CLINICAL INPUT:\n{raw_input}"]
        if options.get("include_ecg") and ecg_data:
            parts.append(f"\nECG DATA:\n{ecg_data}")
        if options.get("include_labs") and lab_data:
            parts.append(f"\nLABORATORY DATA:\n{lab_data}")
        user_message = "\n".join(parts)

    system_prompt = _select_system_prompt(output_type)

    logger.info(
        "Generating clinical document",
        extra={
            "output_type": output_type,
            "has_patient_data": bool(patient_data),
        },
    )

    try:
        response = await client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=0.1,
            max_tokens=3000,
            response_format={"type": "json_object"},
        )

        raw_content = response.choices[0].message.content or "{}"
        elapsed = time.time() - start
        logger.info(f"Clinical document generated in {elapsed:.2f}s")

        try:
            result = json.loads(raw_content)
        except json.JSONDecodeError as jde:
            logger.error(f"JSON parse error: {jde}")
            return {
                "output_type": output_type,
                "note_type": output_type,
                "generated_note": raw_content,
                "sections": {},
                "warnings": ["Model returned malformed JSON. Raw output preserved."],
                "disclaimer": "This note was AI-generated and must be reviewed and approved by the treating physician before clinical or legal use.",
            }

        # Guarantee required fields
        result.setdefault("output_type", output_type)
        result.setdefault("note_type", output_type)
        result.setdefault("generated_note", "")
        result.setdefault("sections", {})
        result.setdefault("warnings", [])
        result.setdefault(
            "disclaimer",
            "This note was AI-generated and must be reviewed and approved by the treating physician before clinical or legal use.",
        )

        return result

    except Exception as exc:
        logger.error(f"Error generating clinical document: {exc}", exc_info=True)
        raise


async def interpret_blood_tests(lab_data: dict) -> dict:
    """
    Standalone blood test interpretation for eGFR, Troponin, CRP, D-Dimer.
    """
    user_message = _build_blood_test_message(lab_data)

    try:
        response = await client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {"role": "system", "content": BLOOD_TEST_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            temperature=0.0,
            max_tokens=1000,
            response_format={"type": "json_object"},
        )

        raw_content = response.choices[0].message.content or "{}"
        result = json.loads(raw_content)
        result.setdefault("interpretations", {})
        result.setdefault("overall_summary", "")
        result.setdefault("warnings", [])
        return result

    except Exception as exc:
        logger.error(f"Blood test interpretation error: {exc}", exc_info=True)
        raise
