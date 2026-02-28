"""
AI Clinical Note Engine
========================
Transforms raw clinical input into structured, legally-safe medical notes
using GPT-4.1-mini with strict conservative/legal wording rules.

Supported note types: SOAP, Progress Note, Discharge Summary,
                      Referral Letter, OPD Note
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
# System prompt — injected once per request
# ---------------------------------------------------------------------------
CLINICAL_NOTE_SYSTEM_PROMPT = """
You are a clinical documentation AI called "AI Clinical Note," embedded in a doctor-assist tool.
Your ONLY job is to transform raw clinical input into a structured, professional, legally-safe medical note.

You ASSIST — the doctor decides. You must NEVER give direct clinical advice, diagnoses, or treatment decisions as final recommendations.

## ABSOLUTE RULES (NEVER BREAK THESE)
- NEVER fabricate clinical data, lab values, or findings not present in the input.
- NEVER output a definitive diagnosis without hedge language.
- NEVER include patient identifiers unless explicitly provided in the input.
- ALWAYS use conservative/hedged language: "consistent with," "suggestive of," "may represent," "cannot exclude."
- NEVER make statements implying negligence or legal liability.
- NEVER use percentage numbers (e.g., "85%") for likelihood.
- ALWAYS include the disclaimer field in every response.
- Return ONLY valid JSON — no backticks, no markdown, no preamble.

## FORMATTING & STYLE RULES
- **Heavy Use of Bullet Points**: Use bullet points for almost all clinical lists (history, symptoms, medications, exam findings, and management plans).
- **Rich Markdown Formatting**: Use **bold text** for critical findings, abnormal values, and primary diagnoses/conclusions.
- **Structural Clarity**: Use clear section headers in ALL CAPS (e.g., SUBJECTIVE, ASSESSMENT) followed by a newline.
- **Spacing**: Always separate major sections in `generated_note` with a double newline for maximum readability.
- **Professional Tone**: Maintain a formal, medical reporting style with high scanability.

## NOTE TYPE → SECTION MAPPING
SOAP                → SUBJECTIVE | OBJECTIVE | ASSESSMENT | PLAN
Progress Note       → INTERVAL HISTORY | EXAMINATION | ASSESSMENT | PLAN
Discharge Summary   → ADMISSION DIAGNOSIS | HOSPITAL COURSE | DISCHARGE CONDITION | DISCHARGE PLAN | FOLLOW-UP
Referral Letter     → REASON FOR REFERRAL | CLINICAL SUMMARY | INVESTIGATIONS | SPECIFIC REQUEST
OPD Note            → PRESENTING COMPLAINT | HISTORY | EXAMINATION | IMPRESSION | MANAGEMENT

## PROCESSING RULES

### 1. DATA NORMALIZATION
- Expand shorthand (e.g., "c/o CP x2d" → "complains of chest pain for 2 days", "HTN" → "hypertension").
- Use bulleted lists for all extracted clinical data points.
- Ensure whitespace between categorized items.

### 2. ECG INTERPRETATION (only if include_ecg=true AND ecg_data is not null)
- Add "ECG Findings:" subsection under OBJECTIVE or relevant section.
- Describe rhythm, rate, intervals, and axis using a bulleted list.

### 3. LAB INTERPRETATION (only if include_labs=true AND lab_data is not null)
- Add "Laboratory Results:" subsection.
- List results clearly; tag abnormal values with **[HIGH]** or **[LOW]** in bold.

### 4. GUIDELINES ALIGNMENT
- Use standard ICD-compatible medical terminology.
- Reference SCOREs (e.g., Wells, HEART) via bolded indicators.

### 5. DIFFERENTIAL DIAGNOSIS (only if include_differential=true)
- Add a bulleted list of 3-5 differentials under ASSESSMENT.
- **PROBABILITY BANDS ONLY**: NEVER use percentages. Use these bands ONLY:
    - High Likelihood
    - Moderate Likelihood
    - Low–Moderate Likelihood
    - Low Likelihood
- **DISTINCT RANKING**: Assign different bands to conditions to show meaningful clinical separation.
- Format: "- **[Likelihood Band]**: **[Diagnosis]** — [brief clinical reasoning]"

## OUTPUT FORMAT (STRICT — valid JSON only)
{
  "note_type": "<selected type>",
  "generated_note": "<full structured note with bolded terms, sections, and frequent bullet points>",
  "sections": {
    "<SECTION_NAME>": "..."
  },
  "warnings": ["<missing critical data or flags, empty array if none>"],
  "disclaimer": "This note was AI-generated and must be reviewed and approved by the treating physician before clinical or legal use."
}

If the input is too vague or incomplete to generate a safe note, populate warnings[] with specific issues and return what partial output is possible.
"""


def _build_user_message(payload: dict) -> str:
    """
    Construct the user-turn message from the structured input payload.
    """
    note_type = payload.get("note_type", "SOAP")
    raw_input = payload.get("raw_input", "")
    ecg_data = payload.get("ecg_data")
    lab_data = payload.get("lab_data")
    options = payload.get("options", {})

    include_ecg = options.get("include_ecg", False) and ecg_data
    include_labs = options.get("include_labs", False) and lab_data
    include_differential = options.get("include_differential", False)

    parts = [
        f"NOTE TYPE: {note_type}",
        f"\nRAW CLINICAL INPUT:\n{raw_input}",
    ]

    if include_ecg:
        parts.append(f"\nECG DATA (include in note):\n{ecg_data}")
    else:
        parts.append("\nECG DATA: Not provided or excluded.")

    if include_labs:
        parts.append(f"\nLABORATORY DATA (include in note):\n{lab_data}")
    else:
        parts.append("\nLABORATORY DATA: Not provided or excluded.")

    parts.append(f"\nINCLUDE DIFFERENTIAL DIAGNOSIS: {'Yes' if include_differential else 'No'}")
    parts.append("\nGenerate the structured clinical note as specified. Return valid JSON only.")

    return "\n".join(parts)


def _validate_payload(payload: dict) -> list[str]:
    """
    Pre-flight validation — returns a list of warning strings.
    Does NOT block generation; warnings are passed into the prompt context.
    """
    warnings = []
    valid_note_types = {
        "SOAP", "Progress Note", "Discharge Summary",
        "Referral Letter", "OPD Note"
    }

    note_type = payload.get("note_type", "")
    if note_type not in valid_note_types:
        warnings.append(
            f"Unknown note_type '{note_type}'. "
            f"Valid types: {', '.join(sorted(valid_note_types))}. Defaulting to SOAP."
        )

    raw_input = payload.get("raw_input", "").strip()
    if not raw_input:
        warnings.append("raw_input is empty. Cannot generate a meaningful clinical note.")
    elif len(raw_input) < 20:
        warnings.append(
            "raw_input is very short. The generated note may be incomplete. "
            "Please provide more clinical detail."
        )

    options = payload.get("options", {})
    if options.get("include_ecg") and not payload.get("ecg_data"):
        warnings.append("include_ecg is true but ecg_data is null or missing. ECG section will be omitted.")
    if options.get("include_labs") and not payload.get("lab_data"):
        warnings.append("include_labs is true but lab_data is null or missing. Lab section will be omitted.")

    return warnings


async def generate_clinical_note(payload: dict) -> dict:
    """
    Main entry point.

    Parameters
    ----------
    payload : dict  — the JSON body matching the AI Clinical Note schema.

    Returns
    -------
    dict — parsed JSON response from the model, always including:
           note_type, generated_note, sections, warnings, disclaimer.
    """
    start = time.time()

    pre_warnings = _validate_payload(payload)

    note_type = payload.get("note_type", "SOAP")
    raw_input = payload.get("raw_input", "").strip()

    # Bail early if there is absolutely nothing to work with
    if not raw_input:
        return {
            "note_type": note_type,
            "generated_note": "",
            "sections": {},
            "warnings": pre_warnings or ["raw_input is empty. No note was generated."],
            "disclaimer": (
                "This note was AI-generated and must be reviewed and approved "
                "by the treating physician before clinical or legal use."
            ),
        }

    user_message = _build_user_message(payload)

    # Inform the model of any pre-flight warnings so it can reflect them
    if pre_warnings:
        warning_note = "\nPRE-FLIGHT WARNINGS (reflect these in your warnings[] array):\n"
        warning_note += "\n".join(f"- {w}" for w in pre_warnings)
        user_message += warning_note

    logger.info(
        "Generating clinical note",
        extra={
            "note_type": note_type,
            "raw_input_length": len(raw_input),
            "include_ecg": payload.get("options", {}).get("include_ecg", False),
            "include_labs": payload.get("options", {}).get("include_labs", False),
        },
    )

    try:
        response = await client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {"role": "system", "content": CLINICAL_NOTE_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            temperature=0.1,        # Near-deterministic for medical documentation
            max_tokens=2500,
            response_format={"type": "json_object"},  # Enforce JSON mode
        )

        raw_content = response.choices[0].message.content or "{}"
        elapsed = time.time() - start
        logger.info(f"Clinical note generated in {elapsed:.2f}s")

        try:
            result = json.loads(raw_content)
        except json.JSONDecodeError as jde:
            logger.error(f"JSON parse error from model output: {jde}")
            return {
                "note_type": note_type,
                "generated_note": raw_content,
                "sections": {},
                "warnings": [
                    "Model returned malformed JSON. Raw output preserved in generated_note.",
                    *pre_warnings,
                ],
                "disclaimer": (
                    "This note was AI-generated and must be reviewed and approved "
                    "by the treating physician before clinical or legal use."
                ),
            }

        # Guarantee required fields are always present
        result.setdefault("note_type", note_type)
        result.setdefault("generated_note", "")
        result.setdefault("sections", {})
        result.setdefault("warnings", [])
        result.setdefault(
            "disclaimer",
            "This note was AI-generated and must be reviewed and approved "
            "by the treating physician before clinical or legal use.",
        )

        # Merge any pre-flight warnings that the model may not have included
        existing_warnings = set(result["warnings"])
        for w in pre_warnings:
            if w not in existing_warnings:
                result["warnings"].append(w)

        return result

    except Exception as exc:
        logger.error(f"Error generating clinical note: {exc}", exc_info=True)
        raise
