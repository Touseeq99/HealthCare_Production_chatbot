"""
ECG Analysis Test Script — GPT-5.4
------------------------------------
Uses GPT-5.4 with:
  - "original" image detail (up to 10.24MP — full ECG fidelity)
  - reasoning.effort = "high" (thinks before answering)
  - Structured JSON output with clinical schema

Usage:
    python ecg_gpt54_test.py --image path/to/ecg.png
    python ecg_gpt54_test.py --image path/to/ecg.png --output result.json
    python ecg_gpt54_test.py --image path/to/ecg.png --model gpt-5.4-pro  # max accuracy

Requirements:
    pip install openai
"""

import argparse
import base64
import json
import sys
from pathlib import Path

from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
# ──────────────────────────────────────────────
# MODEL CONFIG
# ──────────────────────────────────────────────
DEFAULT_MODEL = "gpt-5.4"           # current OpenAI flagship (March 2026)
PRO_MODEL     = "gpt-5.4-pro"       # max accuracy, slower & more expensive

# ──────────────────────────────────────────────
# SYSTEM PROMPT
# ──────────────────────────────────────────────
SYSTEM_PROMPT = """You are a board-certified cardiologist and expert ECG interpreter with over 20 years of clinical experience in a tertiary cardiac care center. You have interpreted over 100,000 ECGs.

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

# ──────────────────────────────────────────────
# USER PROMPT
# ──────────────────────────────────────────────
USER_PROMPT = """Perform a complete systematic ECG interpretation of this 12-lead ECG image.

Return your response as a JSON object with EXACTLY this structure (no markdown, no extra text):
{
  "technical_quality": "string",
  "rate": {
    "ventricular_bpm": "string",
    "atrial_bpm": "string or same as ventricular"
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
  "specific_patterns": ["string", "..."],
  "final_interpretation": "string",
  "differential": ["string or null"],
  "urgency": "routine | urgent | critical",
  "confidence": "low | medium | high",
  "caveats": "string or null"
}"""


def encode_image(image_path: str) -> tuple[str, str]:
    """Encode image to base64 and detect MIME type."""
    ext = Path(image_path).suffix.lower()
    mime_map = {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png",  ".webp": "image/webp",
        ".bmp": "image/bmp",  ".gif":  "image/gif",
    }
    media_type = mime_map.get(ext, "image/jpeg")
    with open(image_path, "rb") as f:
        data = base64.b64encode(f.read()).decode("utf-8")
    return data, media_type


def analyze_ecg(
    image_path: str,
    model: str = DEFAULT_MODEL,
    reasoning_effort: str = "high",
    api_key: str | None = None,
) -> dict:
    """
    Send ECG image to GPT-5.4 and return structured analysis.

    Args:
        image_path:       Path to the ECG image
        model:            OpenAI model string (default: gpt-5.4)
        reasoning_effort: none | low | medium | high | xhigh
        api_key:          OpenAI API key (or OPENAI_API_KEY env var)

    Returns:
        Parsed dict with ECG findings + metadata
    """
    client = OpenAI(api_key=api_key)

    print(f"[*] Model:            {model}")
    print(f"[*] Reasoning effort: {reasoning_effort}")
    print(f"[*] Encoding image:   {image_path}")

    image_data, media_type = encode_image(image_path)

    # ── Build the request ──
    # NOTE: reasoning_effort and temperature are mutually exclusive.
    # If reasoning_effort is set, do NOT pass temperature.
    use_reasoning = reasoning_effort and reasoning_effort != "none"

    request_kwargs = dict(
        model=model,
        max_completion_tokens=8000,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{media_type};base64,{image_data}",
                            "detail": "high",   # "original" only on gpt-5.4+; "high" works on all
                        },
                    },
                    {"type": "text", "text": USER_PROMPT},
                ],
            },
        ],
    )

    if use_reasoning:
        request_kwargs["reasoning_effort"] = reasoning_effort
        print(f"[*] Reasoning mode ON — temperature omitted (they conflict)")
    else:
        request_kwargs["temperature"] = 1

    print("[*] Sending to OpenAI API...")
    try:
        response = client.chat.completions.create(**request_kwargs)
    except Exception as api_err:
        # If reasoning_effort param rejected by SDK version, retry without it
        print(f"[!] API error: {api_err}")
        print("[*] Retrying without reasoning_effort (SDK may be outdated)...")
        request_kwargs.pop("reasoning_effort", None)
        request_kwargs["temperature"] = 1
        response = client.chat.completions.create(**request_kwargs)

    raw_text = (response.choices[0].message.content or "").strip()
    usage    = response.usage

    # Debug: show raw response if empty
    if not raw_text:
        print("[!] WARNING: Model returned empty content.")
        print(f"[!] Finish reason: {response.choices[0].finish_reason}")
        print(f"[!] Full response object: {response}")

    print(f"[*] Tokens — prompt: {usage.prompt_tokens} | completion: {usage.completion_tokens}")
    if hasattr(usage, "completion_tokens_details") and usage.completion_tokens_details:
        reasoning_tokens = getattr(usage.completion_tokens_details, "reasoning_tokens", None)
        if reasoning_tokens:
            print(f"[*] Reasoning tokens: {reasoning_tokens}")

    # ── Strip markdown fences if model adds them ──
    if raw_text.startswith("```"):
        parts = raw_text.split("```")
        raw_text = parts[1]
        if raw_text.startswith("json"):
            raw_text = raw_text[4:]
        raw_text = raw_text.strip()

    try:
        result = json.loads(raw_text)
    except json.JSONDecodeError as e:
        print(f"[!] JSON parse failed: {e}")
        result = {"raw_response": raw_text, "parse_error": str(e)}

    result["_meta"] = {
        "model":              response.model,
        "reasoning_effort":   reasoning_effort,
        "prompt_tokens":      usage.prompt_tokens,
        "completion_tokens":  usage.completion_tokens,
        "image_path":         image_path,
        "image_detail":       "original",
    }

    return result


def print_report(result: dict):
    """Pretty-print the structured ECG report to terminal."""
    print("\n" + "═" * 65)
    print("  ECG ANALYSIS REPORT  —  GPT-5.4")
    print("═" * 65)

    if "parse_error" in result:
        print("[!] JSON parse error — raw model response:")
        print(result.get("raw_response", ""))
        return

    # Rate
    rate = result.get("rate", {})
    ventricular = rate.get("ventricular_bpm", "N/A") if isinstance(rate, dict) else result.get("rate", "N/A")
    atrial      = rate.get("atrial_bpm", "")        if isinstance(rate, dict) else ""

    # Axis
    axis = result.get("axis", {})
    axis_str = (
        f"{axis.get('qrs_degrees', '')} ({axis.get('classification', '')})"
        if isinstance(axis, dict) else str(axis)
    )

    # Intervals
    ivl = result.get("intervals", {})
    pr_str  = ivl.get("pr_ms",  "N/A") if isinstance(ivl, dict) else "N/A"
    qrs_str = ivl.get("qrs_ms", "N/A") if isinstance(ivl, dict) else "N/A"
    qtc_str = ivl.get("qtc_ms", "N/A") if isinstance(ivl, dict) else "N/A"

    rows = [
        ("Technical Quality",   result.get("technical_quality")),
        ("Ventricular Rate",    ventricular + (f" / atrial: {atrial}" if atrial and atrial != ventricular else "")),
        ("Rhythm",              result.get("rhythm")),
        ("Axis",                axis_str),
        ("PR Interval",         pr_str),
        ("QRS Duration",        qrs_str),
        ("QTc Interval",        qtc_str),
        ("P Wave",              result.get("p_wave")),
        ("QRS Morphology",      result.get("qrs_morphology")),
        ("ST Segments",         result.get("st_segments")),
        ("T Waves",             result.get("t_waves")),
        ("U Waves",             result.get("u_waves")),
    ]

    for label, value in rows:
        if value:
            print(f"  {label:<22} {value}")

    patterns = result.get("specific_patterns", [])
    if patterns:
        print(f"\n  Specific Patterns:")
        for p in patterns:
            print(f"    • {p}")

    diff = [d for d in result.get("differential", []) if d]
    if diff:
        print(f"\n  Differential Diagnosis:")
        for d in diff:
            print(f"    • {d}")

    urgency    = result.get("urgency",    "N/A").upper()
    confidence = result.get("confidence", "N/A").upper()
    interp     = result.get("final_interpretation", "N/A")
    caveats    = result.get("caveats")

    urgency_icon = {"CRITICAL": "🔴", "URGENT": "🟡", "ROUTINE": "🟢"}.get(urgency, "⚪")

    print(f"\n  ─────────────────────────────────────────────────────")
    print(f"  INTERPRETATION:  {interp}")
    print(f"  URGENCY:         {urgency_icon} {urgency}")
    print(f"  CONFIDENCE:      {confidence}")
    if caveats:
        print(f"\n  ⚠  CAVEATS: {caveats}")

    meta = result.get("_meta", {})
    print(f"\n  Model: {meta.get('model')}  |  Reasoning: {meta.get('reasoning_effort')}")
    print(f"  Tokens: {meta.get('prompt_tokens')} in → {meta.get('completion_tokens')} out")
    print("═" * 65 + "\n")


# ──────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="ECG Analysis via GPT-5.4 with reasoning",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("--image",    required=True,          help="Path to ECG image (PNG/JPG/WEBP)")
    parser.add_argument("--output",   default=None,           help="Save JSON result to file")
    parser.add_argument("--model",    default=DEFAULT_MODEL,  help=f"Model string (default: {DEFAULT_MODEL})")
    parser.add_argument("--effort",   default="high",         help="Reasoning effort: low|medium|high|xhigh (default: high)")
    parser.add_argument("--key",      default=None,           help="OpenAI API key (or set OPENAI_API_KEY)")
    args = parser.parse_args()

    if not Path(args.image).exists():
        print(f"[ERROR] Image not found: {args.image}")
        sys.exit(1)

    result = analyze_ecg(
        image_path=args.image,
        model=args.model,
        reasoning_effort=args.effort,
        api_key=args.key,
    )

    print_report(result)

    if args.output:
        with open(args.output, "w") as f:
            json.dump(result, f, indent=2)
        print(f"[✓] Saved to {args.output}")


if __name__ == "__main__":
    main()