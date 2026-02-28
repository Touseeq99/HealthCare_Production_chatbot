"""
Differential Diagnosis (DDx) Engine
=====================================
Produces structured, multi-hypothesis differential diagnoses from raw
clinical case data.  All outputs are decision-support only — no definitive
diagnoses, no drug recommendations, no patient-facing content.

Rules enforced identically whether the caller sets flags or not:
  - conservative_reasoning : always ON
  - use_guidelines          : always ON
  - include_red_flags       : always ON
  - ECG / lab sections      : gated by include_ecg / include_labs flags
                              AND non-null data fields
"""

import json
import logging
import time
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv()

client = AsyncOpenAI()
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------
DDX_SYSTEM_PROMPT = """
You are a Differential Diagnosis Assistant — a clinical decision-support AI
embedded in a strictly doctor-only tool. Your sole purpose is to assist
structured clinical reasoning, reduce anchoring bias, and act as a second
checklist.

## ROLE BOUNDARIES — NEVER CROSS THESE
- DO NOT make or confirm final diagnoses.
- DO NOT recommend drugs, doses, or treatment protocols.
- DO NOT generate patient-facing content.
- DO NOT express false certainty.
- DO NOT fabricate lab values, vitals, or clinical data not present in the input.
- ALWAYS label outputs as "Decision Support Only."

## DIFFERENTIAL GENERATION RULES
1. Always generate MULTIPLE differential possibilities — minimum 3, maximum 7.
2. NEVER express a single definitive diagnosis.
3. **NO PERCENTAGES**: NEVER use percentage numbers (e.g., "85%", "50%") for likelihood. It is clinically misleading and implies false precision.
4. **LIKELIHOOD BANDS ONLY**: Use these specific probability bands ONLY:
   - High Likelihood
   - Moderate Likelihood
   - Low–Moderate Likelihood
   - Low Likelihood
5. **DISTINCT RANKING**: Each differential in the list MUST have a distinct likelihood band from the others wherever possible. Do not assign the same likelihood label to multiple conditions (e.g., don't mark two conditions as "Moderate Likelihood") unless it is strictly clinically justified to show they are in the exact same tier. The rank must reflect meaningful clinical separation.
6. Penalize overconfidence — if data is limited, reflect that explicitly in
   likelihood ratings and the uncertainty_statement.
7. Explicitly state uncertainty when present.
8. ECG findings used ONLY if the user prompt indicates include_ecg=true AND
   ecg_data is non-null.
9. Lab data used ONLY if include_labs=true AND lab_data is non-null.
10. Conservative, hedged language is ALWAYS active.
11. Align likelihood estimates with published clinical guidelines where
   applicable (HEART Score, Wells Criteria, TIMI, qSOFA, CURB-65, etc.).
12. The red_flags section is ALWAYS generated — never omit it.

## LANGUAGE RULES
CORRECT phrasing — use these:
  "Consider ordering…"
  "May help clarify diagnosis…"
  "Findings are consistent with…"
  "Cannot exclude…"
  "Supports the possibility of…"

NEVER use:
  "The diagnosis is…"
  "Start treatment with…"
  "Patient has…"
  "Confirmed…"
  Any drug name or dosage

## OUTPUT FORMAT — STRICT JSON, NO MARKDOWN, NO BACKTICKS, NO PREAMBLE
{
  "tool_label": "Differential Diagnosis Assistant (Decision Support)",
  "disclaimer": "This tool supports clinical reasoning and does not provide diagnoses or treatment decisions. For physician use only.",
  "differentials": [
    {
      "rank": 1,
      "condition": "<Condition Name>",
      "likelihood": "High Likelihood | Moderate Likelihood | Low–Moderate Likelihood | Low Likelihood",
      "supporting_evidence": ["<point 1>", "<point 2>"],
      "contradicting_evidence": ["<point 1>", "<point 2>"],
      "guideline_note": "<optional — brief reference to relevant guideline, score, or criteria>"
    }
  ],
  "red_flags": [
    "<Red flag 1>",
    "<Red flag 2>"
  ],
  "suggested_next_steps": [
    "Consider ordering <test> to help clarify <condition>...",
    "May be helpful to assess <finding> given <reasoning>..."
  ],
  "uncertainty_statement": "<Plain-language summary of data gaps or reasoning limitations>",
  "warnings": ["<input gaps or flags — empty array if none>"]
}
"""


# ---------------------------------------------------------------------------
# Payload helpers
# ---------------------------------------------------------------------------

def _build_user_message(payload: dict) -> str:
    """
    Construct the user-turn message.  Only includes ECG / lab blocks when
    the caller has explicitly opted in AND supplied non-null data.
    """
    opts = payload.get("options", {})
    include_ecg = opts.get("include_ecg", False) and payload.get("ecg_data")
    include_labs = opts.get("include_labs", False) and payload.get("lab_data")

    lines = [
        "## CLINICAL CASE DATA",
        f"Case Summary: {payload.get('case_summary', '').strip() or 'Not provided'}",
    ]

    if payload.get("symptoms"):
        lines.append(f"Symptoms: {payload['symptoms'].strip()}")
    if payload.get("vitals"):
        lines.append(f"Vitals: {payload['vitals'].strip()}")
    if payload.get("past_history"):
        lines.append(f"Past Medical History: {payload['past_history'].strip()}")
    if payload.get("risk_factors"):
        lines.append(f"Risk Factors: {payload['risk_factors'].strip()}")

    if include_ecg:
        lines.append(f"\nECG Data (include in analysis):\n{payload['ecg_data'].strip()}")
    else:
        lines.append("\nECG Data: Not provided or excluded from this analysis.")

    if include_labs:
        lines.append(f"\nLaboratory Data (include in analysis):\n{payload['lab_data'].strip()}")
    else:
        lines.append("\nLaboratory Data: Not provided or excluded from this analysis.")

    lines.append(
        "\nGenerate a structured differential diagnosis following the output "
        "format. Return valid JSON only."
    )
    return "\n".join(lines)


def _validate_payload(payload: dict) -> list[str]:
    """
    Pre-flight checks.  Returns warning strings — does NOT block generation.
    """
    warnings: list[str] = []

    case_summary = (payload.get("case_summary") or "").strip()
    if not case_summary:
        warnings.append(
            "case_summary is empty. A meaningful differential cannot be generated "
            "without at minimum an age, sex, and chief complaint."
        )
    elif len(case_summary) < 15:
        warnings.append(
            "case_summary is very brief. Differential quality will be limited. "
            "Please include age, sex, chief complaint, and duration."
        )

    # Warn if no clinical data supplied at all beyond case summary
    data_fields = ["symptoms", "vitals", "lab_data", "ecg_data", "past_history", "risk_factors"]
    non_empty = [f for f in data_fields if (payload.get(f) or "").strip()]
    if not non_empty:
        warnings.append(
            "No supplementary clinical data provided (symptoms, vitals, labs, ECG, "
            "history, or risk factors). Differential is based on case_summary alone — "
            "confidence is limited."
        )

    opts = payload.get("options", {})
    if opts.get("include_ecg") and not payload.get("ecg_data"):
        warnings.append(
            "include_ecg is true but ecg_data is null or missing. "
            "ECG will not be incorporated into this analysis."
        )
    if opts.get("include_labs") and not payload.get("lab_data"):
        warnings.append(
            "include_labs is true but lab_data is null or missing. "
            "Laboratory data will not be incorporated into this analysis."
        )

    return warnings


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def generate_differential(payload: dict) -> dict:
    """
    Generate a structured differential diagnosis.

    Parameters
    ----------
    payload : dict  — validated request body from the API layer.

    Returns
    -------
    dict — parsed JSON response always containing:
           tool_label, disclaimer, differentials, red_flags,
           suggested_next_steps, uncertainty_statement, warnings.
    """
    start = time.time()

    pre_warnings = _validate_payload(payload)

    case_summary = (payload.get("case_summary") or "").strip()

    # Hard bail — nothing to reason about
    if not case_summary:
        return {
            "tool_label": "Differential Diagnosis Assistant (Decision Support)",
            "disclaimer": (
                "This tool supports clinical reasoning and does not provide diagnoses "
                "or treatment decisions. For physician use only."
            ),
            "differentials": [],
            "red_flags": [],
            "suggested_next_steps": [],
            "uncertainty_statement": (
                "No case summary was provided. A differential diagnosis cannot be "
                "generated without at minimum an age, sex, and chief complaint."
            ),
            "warnings": pre_warnings or ["case_summary is empty. No differential generated."],
        }

    user_message = _build_user_message(payload)

    # Inject pre-flight warnings so the model reflects them in output warnings[]
    if pre_warnings:
        user_message += "\n\nPRE-FLIGHT WARNINGS (include these verbatim in your warnings[] array):\n"
        user_message += "\n".join(f"- {w}" for w in pre_warnings)

    logger.info(
        "Generating differential diagnosis",
        extra={
            "case_summary_len": len(case_summary),
            "include_ecg": payload.get("options", {}).get("include_ecg", False),
            "include_labs": payload.get("options", {}).get("include_labs", False),
        },
    )

    try:
        response = await client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {"role": "system", "content": DDX_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            temperature=0.1,        # Near-deterministic for clinical reasoning
            max_tokens=2500,
            response_format={"type": "json_object"},
        )

        raw_content = response.choices[0].message.content or "{}"
        elapsed = time.time() - start
        logger.info(f"Differential generated in {elapsed:.2f}s")

        try:
            result = json.loads(raw_content)
        except json.JSONDecodeError as jde:
            logger.error(f"JSON parse error from model output: {jde}")
            return {
                "tool_label": "Differential Diagnosis Assistant (Decision Support)",
                "disclaimer": (
                    "This tool supports clinical reasoning and does not provide diagnoses "
                    "or treatment decisions. For physician use only."
                ),
                "differentials": [],
                "red_flags": [],
                "suggested_next_steps": [],
                "uncertainty_statement": "Model returned malformed JSON. Raw output could not be parsed.",
                "warnings": [
                    "Model returned malformed JSON. Please retry.",
                    *pre_warnings,
                ],
            }

        # Guarantee all required top-level fields are always present
        result.setdefault("tool_label", "Differential Diagnosis Assistant (Decision Support)")
        result.setdefault(
            "disclaimer",
            "This tool supports clinical reasoning and does not provide diagnoses "
            "or treatment decisions. For physician use only.",
        )
        result.setdefault("differentials", [])
        result.setdefault("red_flags", [])
        result.setdefault("suggested_next_steps", [])
        result.setdefault("uncertainty_statement", "No uncertainty statement was generated.")
        result.setdefault("warnings", [])

        # Merge pre-flight warnings without duplicating
        existing = set(result["warnings"])
        for w in pre_warnings:
            if w not in existing:
                result["warnings"].append(w)

        return result

    except Exception as exc:
        logger.error(f"Error generating differential: {exc}", exc_info=True)
        raise
