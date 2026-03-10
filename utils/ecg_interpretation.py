import base64
import logging
from openai import AsyncOpenAI
import os
from dotenv import load_dotenv
import json

load_dotenv()

client = AsyncOpenAI()
logger = logging.getLogger(__name__)

ECG_PROMPT = """
You are a board-certified cardiac electrophysiologist. Analyze this 12-lead 
ECG image. You MUST follow the EXACT output format below. Do NOT add extra 
text. Do NOT skip any section. Do NOT say "cannot determine" unless truly 
impossible. Be precise and clinical.

═══════════════════════════════════════════
ECG ANALYSIS REPORT
═══════════════════════════════════════════

[1] HEART RATE
━━━━━━━━━━━━━━
Rate: ___ bpm
Category: [ ] Bradycardia <60 | [ ] Normal 60-100 | [ ] Tachycardia >100

[2] PRIMARY RHYTHM
━━━━━━━━━━━━━━━━━
Rhythm: ___________________________
Tick ALL that apply:
[ ] Normal Sinus Rhythm
[ ] Sinus Tachycardia
[ ] Sinus Bradycardia
[ ] Ventricular Bigeminy
[ ] Ventricular Trigeminy
[ ] Atrial Fibrillation
[ ] Other: _______________

[3] PVC ANALYSIS
━━━━━━━━━━━━━━━
PVCs Present: [ ] YES  [ ] NO
If YES:
  Morphology: [ ] LBBB-type  [ ] RBBB-type  [ ] Other
  Axis: [ ] Inferior  [ ] Superior  [ ] Normal
  RVOT Origin Likely: [ ] YES  [ ] NO
  Evidence for RVOT:
    [ ] Tall R in II, III, aVF
    [ ] LBBB morphology in V1
    [ ] Late precordial transition (V4-V5)
    [ ] Monophasic R in inferior leads
  Compensatory Pause: [ ] YES  [ ] NO
  P wave before PVC: [ ] YES  [ ] NO
  QRS width of PVC: ___ ms

[4] INTERVALS
━━━━━━━━━━━━
PR Interval:  ___ ms  [ ] Normal | [ ] Short | [ ] Prolonged
QRS Duration: ___ ms  [ ] Narrow  | [ ] Wide
QT Interval:  ___ ms  [ ] Normal | [ ] Short | [ ] Prolonged
QTc:          ___ ms  [ ] Normal | [ ] Borderline | [ ] Prolonged

[5] CARDIAC AXIS
━━━━━━━━━━━━━━━
QRS Axis: ___ degrees
[ ] Normal (-30 to +90)
[ ] Left Axis Deviation
[ ] Right Axis Deviation
[ ] Extreme Axis

[6] WAVEFORM FINDINGS
━━━━━━━━━━━━━━━━━━━━
P Waves:    [ ] Normal | [ ] Absent | [ ] Abnormal → ___________
QRS:        [ ] Narrow | [ ] Wide   | [ ] Delta wave present
ST Segment: [ ] Normal | [ ] Elevated in: ___ | [ ] Depressed in: ___
T Waves:    [ ] Normal | [ ] Inverted in: ___ | [ ] Peaked in: ___
Q Waves:    [ ] None   | [ ] Pathological in: ___

[7] SPECIAL PATTERNS
━━━━━━━━━━━━━━━━━━━
[ ] LVH (Sokolow-Lyon >35mm)
[ ] RVH
[ ] LBBB
[ ] RBBB
[ ] WPW / Pre-excitation
[ ] Brugada Pattern
[ ] Early Repolarization
[ ] STEMI Pattern
[ ] None of the above

[8] FINAL IMPRESSION
━━━━━━━━━━━━━━━━━━━
Primary Diagnosis: _________________________________
Secondary Findings: _________________________________
Urgency Level: [ ] Routine | [ ] Soon | [ ] ⚠️ URGENT
Recommended Action: _________________________________

═══════════════════════════════════════════
⚠️ DISCLAIMER: For clinical reference only.
Final interpretation must be confirmed by
a licensed physician before any treatment.
═══════════════════════════════════════════

RULES YOU MUST FOLLOW:
- Fill EVERY field
- Use ONLY the format above
- No paragraphs outside the format
- No introductions or conclusions
- Tick boxes must be filled as [✓]
- Unknown values = "Unable to measure"
- If URGENT finding detected, state it in 
  red caps: ⚠️ URGENT: [reason]
"""


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
            model="gpt-5.1-2025-11-13",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": ECG_PROMPT},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime_type};base64,{base64_image}"
                            }
                        }
                    ]
                }
            ],
            max_completion_tokens=2000,
            temperature=1
        )
        
        content = response.choices[0].message.content
        logger.info("Successfully received interpretation from GPT-4o Vision")
        
        return content

    except Exception as e:
        logger.error(f"Error interpreting ECG: {str(e)}")
        raise e

def parse_ecg_response(content: str):
    """
    Parses the GPT response to extract the report.
    Since the new prompt follows a strict text format, we return the entire content 
    as both the clinical summary and raw content for the frontend to display.
    """
    try:
        # The new prompt produces a single formatted clinical report.
        # We return it in clinical_summary to maintain compatibility with existing API consumers.
        return {
            "structured_data": None,
            "clinical_summary": content,
            "raw_content": content
        }
    except Exception as e:
        logger.error(f"Error parsing ECG response: {str(e)}")
        return {
            "structured_data": None,
            "clinical_summary": None,
            "raw_content": content,
            "error": "Failed to parse response structure"
        }
