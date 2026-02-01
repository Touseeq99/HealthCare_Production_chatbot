import time
import json
import os
from datetime import datetime
from openai import AsyncOpenAI
from dotenv import load_dotenv
import asyncio
from Rag_Service.retrieval import query_doc, aquery_doc
import logging

load_dotenv()

# Use AsyncOpenAI for non-blocking streaming
client = AsyncOpenAI()
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

# COMPRESSED SYSTEM PROMPT - More token efficient for lower latency
# COMPRESSED SYSTEM PROMPT - More token efficient for lower latency
CLINICAL_PROMPT = """
You are a Senior Consultant Cardiologist (EP & AF Speciality).
Your task is to provide evidence-based clinical decision support based ONLY on the provided retrieval context.

## Output Structure (STRICTLY FOLLOW THIS ORDER)
You must generate the response using the exact headers and numbering below. Do not reorder or skip sections.

1. **Clinical Takeaway (Synthesis)**
   - Provide 3-5 bullet points synthesizing the key clinical insights.

2. **Research Evidence**
   - Summarize guidelines and trials found strictly in the 'RESEARCH EVIDENCE' context block.
   - If empty, state: "No specific research evidence provided."

3. **Expert Opinion**
   - Summarize clinical nuance and expert views found strictly in the 'EXPERT OPINION' context block.
   - If empty, state: "No specific expert opinion provided."

4. **Patient Perspectives**
   - Summarize patient values and lived experiences found strictly in the 'PATIENT OPINION' context block.
   - If empty, state: "No specific patient perspectives provided."

5. **Decision Context**
   - Provide integration strategies for clinical decision-making.

6. **Limitations**
   - Note any uncertainties or lack of information in the sources.

7. **Emergency Indicators**
   - List any red flags or emergency indicators mentioned in the sources. If none, state: "None mentioned."

8. **Sources Used**
   - List the specific documents/files used, categorized by type.

9. **Guideline Concordance**
   - Format: **Rating:** [Green/Amber/Red] - [1-line justification]

10. **Confidence Meter**
    - Format: **Score:** [0.00-1.00]

11. **Conclusion**
    - Provide a concise CLARA summary.

## Rules
- **No Hallucinations**: If specific information is not in the context, explicitly state that it is missing.
- **Partitioning**: Do not mix information. Research goes in Section 2, Expert in Section 3, Patient in Section 4.
- **Citations**: Cite sources for every claim, e.g., (Source: Document Name).
- **Tone**: Professional, objective, and evidence-based.
"""

CONVERSATIONAL_PROMPT = """
You are a helpful, professional medical AI assistant named CLARA.
Your goal is to assist doctors and patients.

For greetings, pleasantries, or general non-clinical questions (e.g., "Hi", "Hello", "Thanks", "How are you?"), respond politely, briefly, and professionally.
- Do NOT generate a clinical report.
- Do NOT make up medical advice.
- Keep the tone warm but professional.
"""

def is_greeting(text: str) -> bool:
    """Check if the text is a simple greeting or non-clinical pleasantry"""
    greetings = {
        "hi", "hello", "hey", "greetings", "sup", "yo", 
        "good morning", "good afternoon", "good evening",
        "thanks", "thank you", "thx", "bye", "goodbye"
    }
    # Simple normalization
    cleaned = "".join(c for c in text.lower() if c.isalpha() or c.isspace()).strip()
    
    # Check for exact matches or short phrases starting with greeting
    if len(cleaned.split()) <= 3 and any(cleaned.startswith(g) for g in greetings):
        return True
    
    return False

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
        if isinstance(doc, dict):
            if 'document' in doc and isinstance(doc['document'], dict):
                doc_content = doc['document'].get('text', '') or str(doc['document'])
            else:
                doc_content = doc.get('text', '') or doc.get('content', '') or str(doc)
        else:
            doc_content = str(doc)
        
        context_parts.append(f"--- Document {i} ({file_name}) ---\n{doc_content}")
    
    return f"=== {header} ===\n" + "\n\n".join(context_parts) + f"\n=== END {header} ==="

async def doctor_response(question: str, context: str = None) -> str:
    start_total = time.time()
    logger.info(f"Starting doctor_response: {question[:50]}...")
    
    try:
        # Check for greeting/conversational intent
        if is_greeting(question):
            logger.info("Detected greeting intent, skipping RAG.")
            llm_start = time.time()
            stream = await client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": CONVERSATIONAL_PROMPT},
                    {"role": "user", "content": question}
                ],
                stream=True,
                temperature=0.7,
                max_tokens=200
            )
        else:
            # Perform RAG for clinical queries
            rag_start = time.time()
            results = await asyncio.gather(
                aquery_doc(question, 'research'),
                aquery_doc(question, 'expert'),
                aquery_doc(question, 'patient'),
                return_exceptions=True
            )
            rag_end = time.time()
            logger.info(f"PERF: RAG Retrieval took {rag_end - rag_start:.2f}s")
            
            research_result, expert_result, patient_result = results
            
            full_context_parts = []
            for name, res in [("RESEARCH EVIDENCE", research_result), 
                              ("EXPERT OPINION", expert_result), 
                              ("PATIENT OPINION", patient_result)]:
                if isinstance(res, Exception):
                    logger.error(f"{name} retrieval failed: {res}")
                    full_context_parts.append(f"=== {name} ===\nRetrieval failed.")
                else:
                    full_context_parts.append(format_context_section(name, res))
                
            context_text = "\n\n".join(full_context_parts)
            log_rag_interaction(question, context_text)
            
            full_message = f"Context:\n{context_text}\n\nQuestion: {question}"
            
            llm_start = time.time()
            stream = await client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": CLINICAL_PROMPT},
                    {"role": "user", "content": full_message}
                ],
                stream=True,
                temperature=0.1,  
                max_tokens=1500
            )
        
        async def generate():
            first_token = True
            try:
                async for chunk in stream:
                    if first_token:
                        logger.info(f"PERF: First token took {time.time() - llm_start:.2f}s from LLM start")
                        first_token = False
                    if chunk.choices and chunk.choices[0].delta.content:
                        yield chunk.choices[0].delta.content
                logger.info(f"PERF: Total stream took {time.time() - llm_start:.2f}s")
                logger.info(f"PERF: Total Request took {time.time() - start_total:.2f}s")
            except Exception as e:
                logger.error(f"Error in streaming: {e}")
                yield "Sorry, I encountered an error during generation."
        
        return generate()
        
    except Exception as e:
        logger.error(f"Error in doctor_response: {str(e)}", exc_info=True)
        raise

async def doctor_response_with_context(question: str, conversation_context: list = None):
    """Doctor response with both RAG context and conversation history"""
    start_total = time.time()
    logger.info(f"Starting doctor_response_with_context: {question[:50]}...")
    
    try:
        # Check for greeting/conversational intent
        if is_greeting(question):
            logger.info("Detected greeting intent in conversation, skipping RAG.")
            
            messages = [{"role": "system", "content": CONVERSATIONAL_PROMPT}]
            if conversation_context:
                for ctx_msg in conversation_context[-3:]: # Minimal context for greetings
                    messages.append({"role": ctx_msg["role"], "content": ctx_msg["content"]})
            messages.append({"role": "user", "content": question})

            llm_start = time.time()
            stream = await client.chat.completions.create(
                model="gpt-4o",
                messages=messages,
                stream=True,
                temperature=0.7,
                max_tokens=300
            )

        else:
            rag_start = time.time()
            results = await asyncio.gather(
                aquery_doc(question, 'research'),
                aquery_doc(question, 'expert'),
                aquery_doc(question, 'patient'),
                return_exceptions=True
            )
            rag_end = time.time()
            logger.info(f"PERF: RAG Retrieval took {rag_end - rag_start:.2f}s")
            
            research_result, expert_result, patient_result = results
            
            full_context_parts = []
            for name, res in [("RESEARCH EVIDENCE", research_result), 
                              ("EXPERT OPINION", expert_result), 
                              ("PATIENT OPINION", patient_result)]:
                if isinstance(res, Exception):
                    logger.error(f"{name} retrieval failed: {res}")
                    full_context_parts.append(f"=== {name} ===\nRetrieval failed.")
                else:
                    full_context_parts.append(format_context_section(name, res))
                
            rag_context = "\n\n".join(full_context_parts)
            log_rag_interaction(question, rag_context)
            
            messages = [{"role": "system", "content": CLINICAL_PROMPT}]
            
            if conversation_context:
                for ctx_msg in conversation_context[-5:]: # Limit history for latency
                    messages.append({"role": ctx_msg["role"], "content": ctx_msg["content"]})
            
            full_message = f"Research Context:\n{rag_context}\n\nCurrent Question: {question}"
            messages.append({"role": "user", "content": full_message})
            
            llm_start = time.time()
            stream = await client.chat.completions.create(
                model="gpt-4o",
                messages=messages,
                stream=True,
                temperature=0.1,  
                max_tokens=1500
            )
        
        async def generate():
            first_token = True
            try:
                async for chunk in stream:
                    if first_token:
                        logger.info(f"PERF: First token took {time.time() - llm_start:.2f}s from LLM start")
                        first_token = False
                    if chunk.choices and chunk.choices[0].delta.content:
                        yield chunk.choices[0].delta.content
                logger.info(f"PERF: Total stream took {time.time() - llm_start:.2f}s")
                logger.info(f"PERF: Total Request took {time.time() - start_total:.2f}s")
            except Exception as e:
                logger.error(f"Error in streaming: {e}")
                yield "Sorry, I encountered an error during generation."
        
        return generate()
        
    except Exception as e:
        logger.error(f"Error in doctor_response_with_context: {str(e)}", exc_info=True)
        raise
