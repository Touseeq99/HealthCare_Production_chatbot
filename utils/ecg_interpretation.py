import base64
import logging
from openai import AsyncOpenAI
import os
from dotenv import load_dotenv
import json

load_dotenv()

client = AsyncOpenAI()
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# CARDIOLOGIST PERSONA & SYSTEMATIC WORKFLOW
# ──────────────────────────────────────────────
ECG_SYSTEM_PROMPT = """You are a board-certified cardiologist and expert ECG interpreter with over 20 years of clinical experience in a tertiary cardiac care center. You have interpreted over 100,000 ECGs.

Your task is to perform a complete, systematic 12-lead ECG interpretation following the standard cardiologist workflow. Think step by step before arriving at any conclusion.

Systematic interpretation order:
1. TECHNICAL QUALITY — lead quality, artifact, baseline wander, calibration (10mm/mV standard)
2. RATE — calculate ventricular and atrial rate separately if different
3. RHYTHM — identify the dominant rhythm; note any secondary rhythms or ectopy
4. AXIS — frontal plane QRS axis (normal −30° to +90°); note P and T axes if abnormal
5. INTERVALS
   - PR interval (normal 120–200ms; short <120ms, long >200ms)
   - QRS duration (normal <120ms; wide if ≥120ms)
   - QT interval and QTc (Bazett's formula; normal QTc <440ms men, <460ms women)
6. P WAVE — morphology, duration, amplitude, biphasic in V1 (LAE/RAE)
7. QRS MORPHOLOGY
   - Amplitude (LVH: Sokolow-Lyon, Cornell criteria; RVH criteria)
   - Bundle branch blocks (LBBB, RBBB: complete vs incomplete)
   - Fascicular blocks (LAFB, LPFB)
   - Pathological Q waves (location, duration >40ms, depth >25% R)
   - R wave progression (V1–V6); poor R wave progression
   - Delta waves / pre-excitation (WPW)
8. ST SEGMENTS — evaluate each lead systematically
   - Elevation: STEMI (location, territory), early repolarization, Brugada, pericarditis
   - Depression: ischemia, reciprocal changes, strain
9. T WAVES — lead-by-lead if abnormal
   - Inversion: ischemia, strain, PE (S1Q3T3), Wellens syndrome
   - Hyperacute: early STEMI, hyperkalemia
   - Peaked: hyperkalemia, vagal tone
10. U WAVES — presence, polarity (hypokalemia if prominent)
11. SPECIFIC PATTERN CHECKLIST — explicitly check for:
    □ STEMI (anterior/inferior/lateral/posterior/RV) — include culprit artery if identifiable
    □ NSTEMI / UA pattern
    □ LBBB / RBBB / bifascicular / trifascicular
    □ LVH / RVH / biventricular hypertrophy
    □ AF / AFL / SVT / AVNRT / AVRT
    □ VT / VF / accelerated idioventricular
    □ WPW / short PR / delta waves
    □ Long QT / Short QT syndrome
    □ Brugada pattern (Type 1/2/3)
    □ Hyperkalemia / Hypokalemia / Hypercalcemia / Hypocalcemia
    □ Pericarditis (diffuse ST elevation, PR depression)
    □ Pulmonary embolism (S1Q3T3, RV strain, sinus tach)
    □ Pacemaker / ICD spikes — sensing/capture/fusion
12. FINAL INTERPRETATION — concise clinical summary (2-3 sentences max)
13. DIFFERENTIAL — if uncertain, list top 2-3 differentials with reasoning
14. URGENCY — classify: routine / urgent (needs same-day review) / critical (needs immediate action)
15. CONFIDENCE — rate: low / medium / high; list specific caveats if any

Be precise. Use standard cardiology terminology. Never guess — if image quality prevents a reliable finding, explicitly state so."""

ECG_USER_PROMPT = """Perform a complete systematic ECG interpretation of this 12-lead ECG image.

Return your response as a JSON object with EXACTLY this structure (no markdown, no extra text):
{
  "technical_quality": "string",
  "rate": {
    "ventricular_bpm": "string",
    "atrial_bpm": "string"
  },
  "rhythm": "string",
  "axis": {
    "qrs_degrees": "string",
    "classification": "normal | LAD | RAD | extreme"
  },
  "intervals": {
    "pr_ms": "string",
    "qrs_ms": "string",
    "qt_ms": "string",
    "qtc_ms": "string",
    "qtc_formula": "Bazett"
  },
  "p_wave": "string",
  "qrs_morphology": "string",
  "st_segments": "string",
  "t_waves": "string",
  "u_waves": "string",
  "specific_patterns": ["string"],
  "final_interpretation": "string",
  "differential": ["string"],
  "urgency": "routine | urgent | critical",
  "confidence": "low | medium | high",
  "caveats": "string or null"
}"""


async def interpret_ecg(image_bytes: bytes, filename: str):
    """
    Interpret an ECG image using GPT-4o Vision.
    """
    try:
        # Encode image to base64
        base64_image = base64.b64encode(image_bytes).decode('utf-8')
        
        # Determine mime type from filename extension
        ext = filename.split('.')[-1].lower()
        mime_type = f"image/{ext}"
        if ext == 'jpg':
            mime_type = "image/jpeg"

        logger.info(f"Sending ECG image {filename} to GPT-5 Vision for interpretation")
        
        response = await client.chat.completions.create(
            model="gpt-5.4",
            messages=[
                {"role": "system", "content": ECG_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": ECG_USER_PROMPT},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime_type};base64,{base64_image}",
                                "detail": "high"
                            }
                        }
                    ]
                }
            ],
            max_completion_tokens=16000,
            reasoning_effort="high"
        )
        
        content = response.choices[0].message.content
        logger.info("Successfully received interpretation from GPT-4o Vision")
        
        return content

    except Exception as e:
        logger.error(f"Error interpreting ECG: {str(e)}")
        raise e

def parse_ecg_response(content: str):
    """
    Parses the GPT response to extract structured ECG data.
    The response is expected to be a JSON object matching the cardiological schema.
    Returns a dict containing structured_data, a clinical_summary, and raw_content.
    """
    try:
        # Strip markdown fences if present
        cleaned_content = content.strip()
        if cleaned_content.startswith("```"):
            parts = cleaned_content.split("```")
            cleaned_content = parts[1].strip()
            if cleaned_content.startswith("json"):
                cleaned_content = cleaned_content[4:].strip()

        # Try to parse as JSON
        structured_data = json.loads(cleaned_content)
        
        # If successfully parsed, create a nice summary from it
        summary_parts = []
        if "final_interpretation" in structured_data:
            summary_parts.append(f"INTERPRETATION: {structured_data['final_interpretation']}")
        if "urgency" in structured_data:
            icon = {"critical": "🔴", "urgent": "🟡", "routine": "🟢"}.get(structured_data["urgency"].lower(), "⚪")
            summary_parts.append(f"URGENCY: {icon} {structured_data['urgency'].upper()}")
        
        clinical_summary = "\n".join(summary_parts) if summary_parts else content

        return {
            "structured_data": structured_data,
            "clinical_summary": clinical_summary,
            "raw_content": content
        }
    except Exception as e:
        logger.warning(f"Failed to parse ECG JSON: {e}")
        return {
            "structured_data": None,
            "clinical_summary": content,
            "raw_content": content,
            "error": "Format improvement enabled - raw content returned"
        }
