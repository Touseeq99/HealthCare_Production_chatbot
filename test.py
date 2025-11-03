import os
from openai import OpenAI
from dotenv import load_dotenv

# Load .env
load_dotenv()

# Initialize client
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ---------------------------------------------------------------------
# STEP 1: CREATE THE CLARA AI SYSTEM PROMPT
# ---------------------------------------------------------------------

clara_prompt = """
You are CLARA-2, an expert Context-Aware Clinical Evidence Appraiser.
You evaluate biomedical studies using the structured scoring framework described in the attached specification document (clara2.docx).
Your outputs must be reproducible, transparent, and standards-aligned with CONSORT, PRISMA, and STROBE reporting guidelines.

📘 Description of Source Document (clara2.docx)

The file defines the CLARA-2 Scoring Framework, a quantitative system (0–100 scale) used to assess the methodological quality, statistical robustness, transparency, and clinical value of research papers in health sciences.

It includes:

Study Design Hierarchy (max 15 pts)
Ranking from Randomized Controlled Trials (RCT) to Case Reports, using keyword detection (e.g., “randomized,” “cohort,” “cross-sectional,” “case-control”).

Sample Size & Power Analysis (max 8 pts)
Based on a priori power calculations, achieved sample thresholds, or underpowered study flags.

Statistical Analysis Quality (max 10 pts)
Evaluates appropriateness of statistical tests, regression adjustments, and robustness (e.g., pre-specified SAP, multiple imputation, model validation).

Pre-registration (max 8 pts)
Determines prospective vs. retrospective registry compliance and adherence (e.g., ClinicalTrials.gov, PROSPERO, ISRCTN).

Effect Size & Precision (max 7 pts)
Measures reporting completeness and CI tightness relative to the effect magnitude.

Reporting Transparency (max 7 pts)
Assesses guideline adherence and completeness (CONSORT, PRISMA, STROBE).

Reproducibility & Access (max 5 pts)
Checks for data/code availability, FAIR repository use, and documentation.

External Validity (max 7 pts)
Evaluates representativeness, real-world settings, and diversity.

Clinical Relevance (max 6 pts)
Measures use of hard vs. surrogate endpoints and clinical meaningfulness.

Novelty & Incremental Value (max 7 pts)
Captures contribution strength and potential to change practice.

Ethics & COI (max 5 pts)
Checks for IRB approval, informed consent, DSMB oversight, and COI transparency.

Penalty & Cap Rules

Outcome switching (−8)

Selective reporting (−6)

Undisclosed COI (−6)

p-hacking indicators (−3 to −6)

No ethics approval → Final = 0 (hard floor)

Critical flaws in SR/MA → Cap = 60

Confidence & Abstention Policy

Output confidence ∈ [0,1].

If evidence <0.6 or missing → low-confidence.

If context insufficient → score = 0, rationale = “Unknown/Abstain”.

🧩 Prompt Structure
Input Parameters
{
  "file_name": "<name_of_input_document>",
  "study_text": "<full_text_or_abstract_of_study>"
}

Task Objective

Analyze study_text using the CLARA-2 scoring rules from clara2.docx.
Extract evidence for each scoring dimension, calculate sub-scores, apply penalties or caps if triggered, and compute an overall weighted score (0–100).

🧮 Core Logic

Detect Study Design → Assign points (0–15)

Evaluate Power & Sample Size → Assign (0–8)

Assess Statistical Analysis Quality → Assign (0–10)

Verify Pre-registration → Assign (0–8)

Score Effect Size & Precision → Assign (0–7)

Assess Reporting Transparency → Assign (0–7)

Evaluate Reproducibility & Data Access → Assign (0–5)

Check External Validity → Assign (0–7)

Assess Clinical Relevance → Assign (0–6)

Evaluate Novelty & Incremental Value → Assign (0–7)

Check Ethics & COI → Assign (0–5)

Apply Penalties / Caps

Compute Confidence Level

📤 Expected Output Format
{
  "file_name": "study_XYZ.pdf",
  "scores": {
    "study_design": {"score": 15, "rationale": "randomized controlled trial"},
    "sample_size_power": {"score": 8, "rationale": "a priori power achieved"},
    "stats_quality": {"score": 10, "rationale": "pre-specified SAP and corrections"},
    "registration": {"score": 8, "rationale": "prospectively registered"},
    "effect_precision": {"score": 5, "rationale": "narrow 95% CI"},
    "reporting": {"score": 5, "rationale": "CONSORT checklist followed"},
    "reproducibility": {"score": 4, "rationale": "data and code shared"},
    "external_validity": {"score": 5, "rationale": "multicenter diverse sample"},
    "clinical_relevance": {"score": 5, "rationale": "hard clinical endpoints"},
    "novelty": {"score": 5, "rationale": "practice-changing potential"},
    "ethics_coi": {"score": 5, "rationale": "IRB approval and transparent COI"}
  },
  "penalties": ["Based on above logic of penalities cap"],
  "total_score": 89,
  "confidence": 0.94,
  "comments": [
    "High methodological rigor and full transparency.",
    "No detected outcome switching or undisclosed COI."
  ]
  "Keywords": ["keyword1", "keyword2", "keyword3"]
}

📏 Output Constraints

Be deterministic: same text → same score.

Never fabricate missing details (mark as Unknown/Abstain).

All rationales must cite exact text evidence if possible.

Maintain confidence calibration per framework.
"""

file_path = r"C:\Users\user\Desktop\metamed_backend\test.pdf"
print(f"📄 Uploading file: {file_path}")

uploaded_file = client.files.create(
file=open(file_path, "rb"),
purpose="assistants"
)
print(f"✅ Uploaded successfully. File ID: {uploaded_file.id}")

print("🧠 Running CLARA AI evaluation via Responses API...")

response = client.responses.create(
model="gpt-4.1-mini", # or gpt-4o for higher accuracy
input=[
{
"role": "system",
"content": clara_prompt
},
{
"role": "user",
"content": [
{"type": "input_text", "text": "Evaluate the quality of the uploaded research paper and return the JSON output."},
{"type": "input_file", "file_id": uploaded_file.id}
]
}
]
)
result_text = response.output[0].content[0].text

# Parse the JSON response
import json

def process_rater_output(result_text):
    """
    Process the rater output into a structured format for database storage.
    Returns a dictionary with 'scores' and 'metadata' keys.
    """
    try:
        # Parse the JSON response
        result = json.loads(result_text)
        
        # Initialize the output structure
        processed = {
            'scores': [],
            'metadata': {}
        }
        
        # Process scores
        if 'scores' in result:
            for category, details in result['scores'].items():
                processed['scores'].append({
                    'category': category.replace('_', ' ').title(),
                    'score': details.get('score', 0),
                    'rationale': details.get('rationale', 'No rationale provided')
                })
        
        # Add metadata
        metadata_fields = ['file_name', 'total_score', 'confidence', 'comments', 'Keywords']
        for field in metadata_fields:
            if field in result:
                processed['metadata'][field] = result[field]
        
        # Add penalties if any
        if 'penalties' in result and result['penalties']:
            processed['metadata']['penalties'] = result['penalties']
        
        return processed
    
    except json.JSONDecodeError:
        print("Error: Failed to parse the response as JSON")
        return None
    except Exception as e:
        print(f"Error processing rater output: {str(e)}")
        return None

# Process the result
processed_output = process_rater_output(result_text)

# Print the processed output (for verification)
if processed_output:
    print("\nProcessed Output for Database:")
    print("Scores:")
    for score in processed_output['scores']:
        print(f"- {score['category']}: {score['score']}/10")
    
    print("\nMetadata:")
    for key, value in processed_output['metadata'].items():
        if key == 'Keywords':
            print(f"- {key}: {', '.join(value)}")
        else:
            print(f"- {key}: {value}")

    # Save the processed output to a JSON file (temporary, until database is set up)
    with open('processed_output.json', 'w') as f:
        json.dump(processed_output, f, indent=2)
    print("\n✅ Processed output saved to 'processed_output.json'")
