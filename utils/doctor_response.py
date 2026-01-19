import time
import json
import os
from datetime import datetime
from openai import OpenAI
from dotenv import load_dotenv
import asyncio
from Rag_Service.retrieval import query_doc, aquery_doc
import logging
load_dotenv()

client = OpenAI()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def log_rag_interaction(question: str, context: str):
    """Log the question and retrieved context to a JSON file"""
    try:
        log_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "question": question,
            "context": context
        }
        
        log_file = "testinglog.json"
        
        # inconsistent implementation suitable for dev/testing
        if os.path.exists(log_file):
            try:
                with open(log_file, 'r', encoding='utf-8') as f:
                    logs = json.load(f)
                    if not isinstance(logs, list):
                        logs = []
            except Exception:
                logs = []
        else:
            logs = []
            
        logs.append(log_entry)
        
        with open(log_file, 'w', encoding='utf-8') as f:
            json.dump(logs, f, indent=2, ensure_ascii=False)
            
        logger.info(f"Logged RAG interaction to {log_file}")
    except Exception as e:
        logger.error(f"Failed to log RAG interaction: {e}")

# Guideline-concordant color annotation system for propensity rating
prompt ="""
ROLE & SCOPE

You are a Senior Consultant Cardiologist with subspecialty expertise in Cardiac Electrophysiology and Atrial Fibrillation (AF).

Your role is to provide decision-supportive, evidence-based clinical explanations that assist clinicians in understanding what the evidence implies for decision-making, while remaining strictly anchored to the provided sources.

You must integrate insights from three distinct perspectives provided in the context:
1. Research Evidence (Guidelines, RCTs)
2. Expert Opinion (Clinical Experience, Expert Consensus)
3. Patient Opinion (Patient Values, Lived Experience)

🚨 STRICT CONTEXT PARTITIONING
You will receive context data separated into three named blocks:
- === RESEARCH EVIDENCE ===
- === EXPERT OPINION ===
- === PATIENT OPINION ===

When generating the response, you must ONLY use information from the "RESEARCH EVIDENCE" block to write the "Research Evidence" section.
You must ONLY use information from the "EXPERT OPINION" block to write the "Expert Opinion" section.
You must ONLY use information from the "PATIENT OPINION" block to write the "Patient Perspectives" section.
DO NOT Mix sources across these sections. If a block says "No information found", state "No specific information provided in sources".

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
1️⃣ Clinical Takeaway (Synthesis)

3–5 concise bullet points

Synthesize key insights from Research, Expert, and Patient perspectives.

Frame as “what the evidence suggests for clinical decision-making”

2️⃣ Research Evidence (Standard Guidelines)

Summary of relevant guidelines and trials ONLY from the "RESEARCH EVIDENCE" context block.

3️⃣ Expert Opinion (Clinical Nuance)

Summary of expert insights ONLY from the "EXPERT OPINION" context block.

Highlight practical considerations or advanced management strategies.

4️⃣ Patient Perspectives (Lived Experience)

Summary of patient values, concerns, and experiences ONLY from the "PATIENT OPINION" context block.

Highlight compliance issues, quality of life, or patient preferences.

5️⃣ Clinical Decision Context

Explain how to integrate these three perspectives for decision-making.

Highlight:

Applicability conditions

Patient characteristics mentioned in sources

Situations where perspectives might conflict or align

6️⃣ Limitations & Uncertainty

Explicitly list limitations stated in the sources

Additional limitations allowed only if clearly labeled

No speculative risk claims

7️⃣ When Immediate Medical Attention Is Required

Include only emergency indicators stated in sources

If absent:

“Emergency indications are not discussed in the provided sources.”

8️⃣ Sources Used

List only sources cited, categorized by:
- Research
- Expert Opinion
- Patient Opinion

9️⃣ Guideline Concordance Color Rating

Based only on strength and completeness of supplied sources:

🟢 Green (≥0.80): Strong, consistent guideline-level evidence

🟠 Amber (0.50–0.79): Partial or indirect evidence

🔴 Red (<0.50): Limited, conflicting, or absent evidence

Provide 1-line justification referencing source quality.

🔟 Confidence Meter

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

def format_context_section(header: str, query_result: dict) -> str:
    """Helper to format a specific context section"""
    if not query_result or not isinstance(query_result, dict):
        return f"=== {header} ===\nNo information found."
    
    reranked_docs = query_result.get('reranked_docs', [])
    file_names = query_result.get('file_names', [])
    
    if not reranked_docs:
        return f"=== {header} ===\nNo relevant documents found."
        
    context_parts = []
    for i, (doc, file_name) in enumerate(zip(reranked_docs, file_names), 1):
        # Handle PineconeRerank nested structure
        if isinstance(doc, dict):
            if 'document' in doc and isinstance(doc['document'], dict):
                doc_content = doc['document'].get('text', '') or str(doc['document'])
            else:
                doc_content = doc.get('text', '') or doc.get('content', '') or str(doc)
        else:
            doc_content = str(doc)
        
        # Add clear source attribution within the context block
        context_parts.append(f"--- Document {i} ({file_name}) ---\n{doc_content}")
    
    joined_docs = "\n\n".join(context_parts)
    return f"=== {header} ===\n{joined_docs}\n=== END {header} ==="

async def doctor_response(question: str, context: str = None) -> str:
    logger.info(f"Starting doctor_response with question: {question[:100]}...")
    
    try:
        # Prepare the message with context if provided
        logger.info("Calling aquery_doc for 3 indices...")
        rag_start_time = time.time()
        
        # Parallel retrieval
        results = await asyncio.gather(
            aquery_doc(question, 'research'),
            aquery_doc(question, 'expert'),
            aquery_doc(question, 'patient'),
            return_exceptions=True
        )
        
        research_result, expert_result, patient_result = results
        
        rag_duration = time.time() - rag_start_time
        logger.info(f"RAG Retrieval time (Parallel): {rag_duration:.4f} seconds")
        
        # Handle exceptions if any retrieval failed
        full_context_parts = []
        
        if isinstance(research_result, Exception):
            logger.error(f"Research retrieval failed: {research_result}")
            full_context_parts.append("=== RESEARCH EVIDENCE ===\nRetrieval failed.")
        else:
            full_context_parts.append(format_context_section("RESEARCH EVIDENCE", research_result))
            
        if isinstance(expert_result, Exception):
            logger.error(f"Expert retrieval failed: {expert_result}")
            full_context_parts.append("=== EXPERT OPINION ===\nRetrieval failed.")
        else:
            full_context_parts.append(format_context_section("EXPERT OPINION", expert_result))
            
        if isinstance(patient_result, Exception):
            logger.error(f"Patient retrieval failed: {patient_result}")
            full_context_parts.append("=== PATIENT OPINION ===\nRetrieval failed.")
        else:
            full_context_parts.append(format_context_section("PATIENT OPINION", patient_result))
            
        context_text = "\n\n".join(full_context_parts)
        logger.info(f"Context formatted, length: {len(context_text)}")
        
        # Log interaction
        log_rag_interaction(question, context_text)
        
        full_message = f"Context:\n{context_text}\n\nQuestion: {question}"
        
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
            max_tokens=1500
        )
        logger.info("OpenAI stream created successfully")
        
        # Create an async generator
        async def generate():
            try:
                logger.info("Starting to stream response...")
                for chunk in stream:
                    if chunk.choices and chunk.choices[0].delta.content is not None:
                        content = chunk.choices[0].delta.content
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
        logger.info("Calling aquery_doc for 3 indices...")
        rag_start_time = time.time()
        
        # Parallel retrieval
        results = await asyncio.gather(
            aquery_doc(question, 'research'),
            aquery_doc(question, 'expert'),
            aquery_doc(question, 'patient'),
            return_exceptions=True
        )
        
        research_result, expert_result, patient_result = results
        
        rag_duration = time.time() - rag_start_time
        logger.info(f"RAG Retrieval time (Parallel): {rag_duration:.4f} seconds")
        
        # Format context parts
        full_context_parts = []
        
        if isinstance(research_result, Exception):
            logger.error(f"Research retrieval failed: {research_result}")
            full_context_parts.append("=== RESEARCH EVIDENCE ===\nRetrieval failed.")
        else:
            full_context_parts.append(format_context_section("RESEARCH EVIDENCE", research_result))
            
        if isinstance(expert_result, Exception):
            logger.error(f"Expert retrieval failed: {expert_result}")
            full_context_parts.append("=== EXPERT OPINION ===\nRetrieval failed.")
        else:
            full_context_parts.append(format_context_section("EXPERT OPINION", expert_result))
            
        if isinstance(patient_result, Exception):
            logger.error(f"Patient retrieval failed: {patient_result}")
            full_context_parts.append("=== PATIENT OPINION ===\nRetrieval failed.")
        else:
            full_context_parts.append(format_context_section("PATIENT OPINION", patient_result))
            
        rag_context = "\n\n".join(full_context_parts)
        logger.info(f"RAG context formatted, length: {len(rag_context)}")
        
        # Log interaction
        log_rag_interaction(question, rag_context)
        
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
        full_message = f"Previous Conversation Context: Available\n\nResearch Context:\n{rag_context}\n\nCurrent Question: {question}"
        logger.info(f"Full message prepared with RAG context, length: {len(full_message)}")
        
        messages.append({"role": "user", "content": full_message})
        
        logger.info("Creating OpenAI stream with conversation context...")
        # Create a streaming chat completion
        stream = client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            stream=True,
            temperature=0.2,  
            max_tokens=1500
        )
        logger.info("OpenAI stream created successfully")
        
        # Create an async generator
        async def generate():
            try:
                logger.info("Starting to stream response...")
                for chunk in stream:
                    if chunk.choices and chunk.choices[0].delta.content is not None:
                        content = chunk.choices[0].delta.content
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
