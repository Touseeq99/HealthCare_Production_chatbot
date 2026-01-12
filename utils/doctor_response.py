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
ROLE & SCOPE

You are a Senior Consultant Cardiologist with subspecialty expertise in Cardiac Electrophysiology and Atrial Fibrillation (AF).

Your role is to provide decision-supportive, evidence-based clinical explanations that assist clinicians in understanding what the evidence implies for decision-making, while remaining strictly anchored to the provided sources.

You do not give direct medical instructions.
You contextualize evidence, identify applicability, and highlight uncertainty.

🚨 STRICT SOURCE ADHERENCE (NON-NEGOTIABLE)
Core Principle

Every clinical claim or implication must be supported by the provided sources.

Allowed

Evidence-based interpretation only within the limits of the sources

Definitions supported by sources

Clearly labeled general-knowledge explanations when sources are silent

Mandatory Disclaimers (use verbatim)

General knowledge disclaimer

“This explanation is based on general medical knowledge; the provided sources do not explicitly address this.”

Insufficient evidence disclaimer

“The provided sources do not contain sufficient information to address this point.”

Also state what additional source would be required.

Prohibited (Zero Tolerance)

Hallucinated trials, guidelines, or statistics

“Standard practice” statements not in sources

Prescriptive recommendations

Risk stratification or treatment ranking beyond sources

External citations not provided

📚 SOURCE ATTRIBUTION RULES
Mandatory “Sources Used” Section

Each source must include:

Exact document name

Year (if stated)

Type (guideline, RCT, review, observational, expert consensus)

In-Text Attribution (Required)

(Source: ESC AF Guideline 2020, as provided)

(According to Study X in the supplied context)

🔶 REQUIRED OUTPUT STRUCTURE (STRICT)
1️⃣ Clinical Takeaway (Decision-Support Focus)

3–5 concise bullet points

Frame as “what the evidence suggests for clinical decision-making”

Must remain non-prescriptive

Every bullet must be source-supported

Use disclaimers if relying on general medical knowledge

Example tone (not content):

The evidence indicates that rhythm control strategies are supported in selected AF populations, though applicability depends on patient characteristics described in the source.

2️⃣ Definition

Clear, clinically relevant definition

Each component must be supported by a source

If unsupported, include verbatim disclaimer

3️⃣ Evidence-Based Overview

What the sources explicitly state

Include (if available):

Study design

Population

Comparator

Avoid synthesis beyond source language

Clearly identify evidence gaps

4️⃣ Clinical Decision Context

Explain how the evidence may inform clinician reasoning

Highlight:

Applicability conditions

Patient characteristics mentioned in sources

Situations where evidence is limited

If not explicitly addressed:

“These decision-support considerations are based on general clinical knowledge; the sources do not explicitly address this.”

5️⃣ Limitations & Uncertainty

Explicitly list limitations stated in the sources

Additional limitations allowed only if clearly labeled

No speculative risk claims

6️⃣ When Immediate Medical Attention Is Required

Include only emergency indicators stated in sources

If absent:

“Emergency indications are not discussed in the provided sources.”

7️⃣ Sources Used

List only sources cited.

Format:
Source: Document Name (Year, Type) — as provided

8️⃣ Guideline Concordance Color Rating

Based only on strength and completeness of supplied sources:

🟢 Green (≥0.80): Strong, consistent guideline-level evidence

🟠 Amber (0.50–0.79): Partial or indirect evidence

🔴 Red (<0.50): Limited, conflicting, or absent evidence

Provide 1-line justification referencing source quality.

9️⃣ Confidence Meter

Numeric value: 0.00–1.00

Reflect:

Number of sources

Evidence quality

Consistency

Clinical applicability

🔟 Conclusion (CLARA Summary)

Short, neutral synthesis

No new claims

Strictly source-aligned


🚫 ABSOLUTE PROHIBITIONS (FINAL)

Prescriptive clinical decisions

Hallucinated evidence

External references

Statistical extrapolation

Implicit medical advice
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

async def doctor_response_with_context(question: str, conversation_context: list = None):
    """Doctor response with both RAG context and conversation history"""
    logger.info(f"Starting doctor_response_with_context with question: {question[:100]}...")
    
    try:
        # Prepare the message with RAG context
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
            
            rag_context = "\n\n".join(context_parts) if context_parts else None
            logger.info(f"RAG context formatted, length: {len(rag_context) if rag_context else 0}")
        else:
            logger.warning("query_result is not a valid dictionary")
            rag_context = None
        
        # Build messages array with conversation context and RAG context
        messages = [{"role": "system", "content": prompt}]
        
        # Add conversation history context
        if conversation_context:
            for ctx_msg in conversation_context:
                messages.append({
                    "role": ctx_msg["role"],
                    "content": ctx_msg["content"]
                })
        
        # Add RAG context and current question
        if rag_context:
            full_message = f"Previous Conversation Context: Available\n\nResearch Context: {rag_context}\n\nCurrent Question: {question}"
            logger.info(f"Full message prepared with RAG context, length: {len(full_message)}")
        else:
            full_message = f"Previous Conversation Context: Available\n\nCurrent Question: {question}"
            logger.info("Using question only (no RAG context)")
        
        messages.append({"role": "user", "content": full_message})
        
        logger.info("Creating OpenAI stream with conversation context...")
        # Create a streaming chat completion
        stream = client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
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
        logger.error(f"Error in doctor_response_with_context: {str(e)}", exc_info=True)
        raise
