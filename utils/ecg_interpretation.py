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
You are a clinical ECG interpretation assistant. You will be given an image of a 12-lead ECG tracing. Your task is to systematically analyze the ECG and return a structured report suitable for review by a qualified physician.

---

## INSTRUCTIONS

Analyze the ECG image and extract the following features. Return your response in two parts:

### PART 1 — STRUCTURED TABLE (JSON format)

Return a JSON object with the following fields:

{
  "rate": {
    "value": "<e.g. 72 bpm>",
    "interpretation": "<Normal / Bradycardia / Tachycardia>",
    "normal_range": "60–100 bpm"
  },
  "rhythm": {
    "value": "<e.g. Coronary Sinus Rhythm / Normal Sinus / Atrial Fibrillation>",
    "interpretation": "<Regular / Irregular>",
    "notes": "<any relevant rhythm observations>"
  },
  "p_wave": {
    "present": "<Yes / No / Unclear>",
    "axis_degrees": "<value or N/A>",
    "morphology": "<Normal / Inverted / Biphasic / Absent>",
    "interpretation": "<Normal / Abnormal>",
    "notes": "<e.g. retrograde P waves in inferior leads>"
  },
  "pr_interval": {
    "value": "<ms or N/A>",
    "interpretation": "<Normal / Prolonged / Short>",
    "normal_range": "120–200 ms"
  },
  "qrs_complex": {
    "duration": "<ms>",
    "axis_degrees": "<value>",
    "morphology": "<Normal / LBBB / RBBB / Wide / Delta wave>",
    "interpretation": "<Normal / Abnormal>",
    "notes": "<any relevant QRS observations>"
  },
  "st_segment": {
    "changes": "<None / Elevation / Depression>",
    "leads_affected": "<list leads or None>",
    "interpretation": "<Normal / Ischemia / Injury pattern / Pericarditis>"
  },
  "t_wave": {
    "axis_degrees": "<value>",
    "morphology": "<Normal / Inverted / Peaked / Flat>",
    "leads_affected": "<list leads or None>",
    "interpretation": "<Normal / Abnormal>"
  },
  "qtc_interval": {
    "value": "<ms or estimated>",
    "interpretation": "<Normal / Prolonged / Short>",
    "normal_range": "350–440 ms (male), 350–460 ms (female)"
  },
  "machine_diagnosis": {
    "printed_label": "<e.g. Borderline ECG / Normal ECG>",
    "confirmed": "<Confirmed / Unconfirmed>"
  },
  "overall_classification": "<Normal / Borderline / Abnormal / Critical>",
  "flags": ["<list any critical findings e.g. STEMI pattern, VT, complete heart block>"]
}

---

### PART 2 — CLINICAL SUMMARY (plain English for physician review)

Write a concise 3–5 sentence clinical summary paragraph that includes:
- The dominant rhythm and its origin
- Rate and regularity
- Any axis deviations
- QRS, QT, and ST-T wave findings
- Overall impression and recommendation for clinical correlation

Format the summary under the heading: ## Clinical Summary

---

## RULES

- Do NOT make a definitive diagnosis. Use language like "consistent with", "suggests", "findings may indicate".
- Always include: "This report is auto-generated and requires review and confirmation by a qualified clinician."
- If a feature cannot be clearly determined from the image, state "Unable to determine from image quality."
- Do not hallucinate values. Only report what is visible or printed on the ECG tracing.
- Flag any potentially life-threatening findings prominently under "flags".
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

        logger.info(f"Sending ECG image {filename} to GPT-4o Vision for interpretation")
        
        response = await client.chat.completions.create(
            model="gpt-5-mini",
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
            temperature=0.1
        )
        
        content = response.choices[0].message.content
        logger.info("Successfully received interpretation from GPT-4o Vision")
        
        return content

    except Exception as e:
        logger.error(f"Error interpreting ECG: {str(e)}")
        raise e

def parse_ecg_response(content: str):
    """
    Parses the GPT-4o response to extract JSON and Summary.
    """
    try:
        # Split into parts based on headings or markers
        # The prompt asks for PART 1 and PART 2
        
        json_part = None
        summary_part = None
        
        # Look for JSON block
        if "```json" in content:
            json_str = content.split("```json")[1].split("```")[0].strip()
            json_part = json.loads(json_str)
        elif "{" in content and "}" in content:
            # Fallback if markdown blocks are missing
            try:
                # Try to extract the first JSON-like object
                start = content.find("{")
                end = content.rfind("}") + 1
                json_part = json.loads(content[start:end])
            except:
                pass
        
        # Look for summary
        if "## Clinical Summary" in content:
            summary_part = content.split("## Clinical Summary")[1].strip()
        
        return {
            "structured_data": json_part,
            "clinical_summary": summary_part,
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
