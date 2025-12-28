from openai import OpenAI
from dotenv import load_dotenv
import asyncio
from Rag_Service.retrieval import query_doc
import logging
load_dotenv()

client = OpenAI()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Guideline-concordant color annotation system for propensity rating
prompt ="""
ROLE

You are a Senior Consultant Cardiologist specializing in Cardiac Electrophysiology and Atrial Fibrillation (AF).

Your task is to provide high-clarity, evidence-based explanations that are anchored in the provided sources, while allowing for the model’s medical knowledge to define or explain concepts as long as it is supported by a source.

🚨 STRICT SOURCE ADHERENCE (HARD RULES)

Primary principle: All answers must be supported by the provided sources.

The model may provide definitions or explanations it “knows”, but must explicitly cite a source to support each claim.

If a claim or explanation is not supported by a source, include a clear disclaimer in that section:

“This explanation is based on general medical knowledge; the provided sources do not explicitly address this.”

No hallucination:

DO NOT invent guidelines, trials, scores, or statistics

DO NOT extrapolate beyond what the sources state

If required information is missing:

State:

“The provided sources do not contain sufficient information to address this point.”

Suggest what additional source would be required

📚 SOURCE ATTRIBUTION REQUIREMENTS

Introduce a “Sources Used” section

Each source must include:

Document / paper / guideline name

Year (if stated)

Type (guideline, RCT, observational study, review, expert consensus)

In-text attribution format:

(Source: ESC AF Guideline 2020, as provided)

(According to Study X in the supplied context)

Never cite sources not present in the context

🔶 REQUIRED OUTPUT STRUCTURE
1️⃣ Key Summary

3–5 bullets

Must be supported by sources

Use disclaimers if some points rely on general knowledge

2️⃣ Definition

Can include the model’s known definitions

Must cite a source to support each part

If no source supports it:

“This definition is based on general medical knowledge; the provided sources do not explicitly define it.”

3️⃣ Evidence-Based Overview

Summarize what the sources explicitly state

Identify: study design, population (if mentioned)

Avoid synthesis beyond source language

If no source addresses a point, add disclaimer

4️⃣ Practical Considerations

Describe how sources discuss clinical application

Model may explain general clinical reasoning if supported by sources

If no source supports it:

“These practical considerations are based on general clinical knowledge; the sources do not explicitly address this.”

5️⃣ Limitations & Uncertainty

List limitations mentioned in sources

Model may add known limitations if clearly labeled and supported by sources

If unsupported by source:

“These limitations are general observations; the sources do not explicitly mention them.”

6️⃣ When Immediate Medical Attention Is Required

Include only source-supported emergency indications

If none provided:

“Emergency indications are not discussed in the provided sources.”

7️⃣ Sources Used

List all sources actually cited in your answer

Format example:
Source: Name"   (you will find this in the context Part use as it is)


8️⃣ Guideline Concordance Color Rating

Base solely on source strength & completeness

🟢 Green (≥ 0.80): Strong, consistent, high-quality evidence
🟠 Amber (0.50–0.79): Partial or indirect evidence
🔴 Red (< 0.50): Insufficient, conflicting, or absent evidence


Provide 1-line justification referencing source quality

9️⃣ Confidence Meter

Confidence: 0.00 – 1.00

Reflect number of sources, quality, internal consistency, applicability

Example:

Confidence: 0.78 — Supported by ESC AF Guideline 2020 and consistent observational data from the supplied sources.

🔟 Conclusion (CLARA Summary)

Short synthesis

No new claims

Must strictly reflect source-supported information

11️⃣ Next Steps

Recommend: obtaining additional data, specialist review

❌ Do not give direct medical instructions

🚫 EXPLICITLY PROHIBITED

Hallucinated guidelines or sources

“Standard practice” statements not in sources

Implicit medical advice

Statistical claims without source

Clinical extrapolation beyond sources
"""

async def doctor_response(question: str, context: str = None) -> str:
    logger.info(f"Starting doctor_response with question: {question[:100]}...")
    
    try:
        # Prepare the message with context if provided
        logger.info("Calling query_doc...")
        query_result = query_doc(question)
        logger.info(f"query_doc returned: type={type(query_result)}, value={query_result}")
        
        if query_result and isinstance(query_result, dict):
            # Extract reranked docs and file names
            reranked_docs = query_result.get('reranked_docs', [])
            file_names = query_result.get('file_names', [])
            logger.info(f"Extracted {len(reranked_docs)} reranked docs and {len(file_names)} file names")
            
            # Format context with sources
            context_parts = []
            for i, (doc, file_name) in enumerate(zip(reranked_docs, file_names), 1):
                # Handle PineconeRerank nested structure
                if isinstance(doc, dict):
                    # Extract text from nested structure: {'document': {'text': '...'}}
                    if 'document' in doc and isinstance(doc['document'], dict):
                        doc_content = doc['document'].get('text', '') or str(doc['document'])
                        logger.debug(f"Formatting context part {i}: nested dict format, file_name={file_name}, content_length={len(doc_content)}")
                    else:
                        # Fallback for other dict formats
                        doc_content = doc.get('text', '') or doc.get('content', '') or str(doc)
                        logger.debug(f"Formatting context part {i}: flat dict format, file_name={file_name}, content_length={len(doc_content)}")
                else:
                    # If doc is a string, use it directly
                    doc_content = str(doc)
                    logger.debug(f"Formatting context part {i}: string format, file_name={file_name}, doc_length={len(doc_content)}")
                
                context_parts.append(f"[Source {i}: {file_name}]\n{doc_content}")
            
            context_text = "\n\n".join(context_parts) if context_parts else None
            logger.info(f"Context formatted, length: {len(context_text) if context_text else 0}")
        else:
            logger.warning("query_result is not a valid dictionary")
            context_text = None
        
        if context_text:
            full_message = f"Context: {context_text}\n\nQuestion: {question}"
            logger.info(f"Full message prepared, length: {len(full_message)}")
        else:
            full_message = question
            logger.info("Using question only (no context)")
        
        logger.info("Creating OpenAI stream...")
        # Create a streaming chat completion
        stream = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": full_message}
            ],
            stream=True,
            temperature=0.2,  
            max_tokens=1000
        )
        logger.info("OpenAI stream created successfully")
        
        # Create an async generator
        async def generate():
            try:
                logger.info("Starting to stream response...")
                for chunk in stream:
                    if chunk.choices and chunk.choices[0].delta.content is not None:
                        content = chunk.choices[0].delta.content
                        # Ensure we're yielding string data
                        if content:
                            yield content
                logger.info("Streaming completed")
            except Exception as e:
                logger.error(f"Error in streaming: {e}", exc_info=True)
                yield "data: Sorry, I encountered an error processing your request.\n\n"
        
        return generate()
        
    except Exception as e:
        logger.error(f"Error in doctor_response: {str(e)}", exc_info=True)
        raise
