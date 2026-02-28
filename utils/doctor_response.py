import time
from openai import AsyncOpenAI
from dotenv import load_dotenv
import asyncio
from Rag_Service.retrieval import query_doc, aquery_doc, aquery_doc_with_embedding, embed_query
import logging

load_dotenv()

# Use AsyncOpenAI for non-blocking streaming
client = AsyncOpenAI()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def log_rag_interaction(question: str, context: str):
    """Log the question and retrieved context using structured logging (not file I/O)"""
    try:
        logger.info(
            "RAG interaction",
            extra={
                "rag_question": question[:200],
                "rag_context_length": len(context),
                "rag_context_preview": context[:500]
            }
        )
    except Exception as e:
        logger.error(f"Failed to log RAG interaction: {e}")

# COMPRESSED SYSTEM PROMPT - More token efficient for lower latency
CLINICAL_PROMPT = """
You are a Senior Consultant Cardiologist (EP & AF Speciality).
Your task is to provide evidence-based clinical decision support based ONLY on the provided retrieval context.

## Output Structure (STRICTLY FOLLOW THIS ORDER)
You must generate the response using the exact headers and numbering below. Do not reorder or skip sections. Use **bold text** for critical findings and key clinical terms.

1. **Clinical Takeaway (Synthesis)**
   - Provide 3-5 high-impact bullet points synthesizing the key clinical insights.
   - Use **bold** for primary recommendations/findings.

2. **Research Evidence**
   - Use a clear bulleted list to summarize guidelines and trials found strictly in the 'RESEARCH EVIDENCE' context block.
   - Format: "- **[Trial/Guideline Name]**: [One-line summary of findings]"
   - If empty, state: "No specific research evidence provided."

3. **Expert Opinion**
   - Use a bulleted list to summarize clinical nuance and expert views found strictly in the 'EXPERT OPINION' context block.
   - Focus on practical applications and clinical judgment.
   - If empty, state: "No specific expert opinion provided."

4. **Patient Perspectives**
   - Use a bulleted list to summarize patient values and lived experiences found strictly in the 'PATIENT OPINION' context block.
   - If empty, state: "No specific patient perspectives provided."

5. **Decision Context**
   - Synthesize the above via a bulleted list of integration strategies for clinical decision-making.

6. **Limitations**
   - Note any uncertainties or lack of information in the sources using bullet points.

7. **Emergency Indicators**
   - Use a bolded, bulleted list of any red flags or emergency indicators mentioned in the sources.
   - If none, state: "None mentioned."

8. **Sources Used**
   - Catagorize sources by type using bullet points:
     - Research: [Source 1, Source 2]
     - Expert: [Source A, Source B]
     - Patient: [Source X]

9. **Guideline Concordance**
   - Format: **Rating:** [Green/Amber/Red] - [1-line justification in bold]

10. **Confidence Meter**
    - Format: **Score:** [0.00-1.00] - [Brief rationale for the score]

11. **Conclusion**
    - Provide a concise 2-3 sentence CLARA summary closing the report.

## Rules
- **Formatting**: Always maximize readability with bullet points and **bold text** for emphasis.
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
                model="gpt-4.1-mini",
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
            # Step 1: Compute embedding ONCE (saves ~400ms vs computing 3x)
            rag_start = time.time()
            query_embedding = await embed_query(question)
            embed_time = time.time()
            logger.info(f"PERF: Embedding computed in {embed_time - rag_start:.2f}s")
            
            # Step 2: Search all 3 indices in parallel using pre-computed embedding
            results = await asyncio.gather(
                aquery_doc_with_embedding(question, query_embedding, 'research'),
                aquery_doc_with_embedding(question, query_embedding, 'expert'),
                aquery_doc_with_embedding(question, query_embedding, 'patient'),
                return_exceptions=True
            )
            rag_end = time.time()
            logger.info(f"PERF: RAG Retrieval took {rag_end - rag_start:.2f}s (embedding: {embed_time - rag_start:.2f}s, search: {rag_end - embed_time:.2f}s)")
            
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
                model="gpt-4.1-mini",
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
                model="gpt-4.1-mini",
                messages=messages,
                stream=True,
                temperature=0.7,
                max_tokens=300
            )

        else:
            # Step 1: Compute embedding ONCE (saves ~400ms vs computing 3x)
            rag_start = time.time()
            query_embedding = await embed_query(question)
            embed_time = time.time()
            logger.info(f"PERF: Embedding computed in {embed_time - rag_start:.2f}s")
            
            # Step 2: Search all 3 indices in parallel using pre-computed embedding
            results = await asyncio.gather(
                aquery_doc_with_embedding(question, query_embedding, 'research'),
                aquery_doc_with_embedding(question, query_embedding, 'expert'),
                aquery_doc_with_embedding(question, query_embedding, 'patient'),
                return_exceptions=True
            )
            rag_end = time.time()
            logger.info(f"PERF: RAG Retrieval took {rag_end - rag_start:.2f}s (embedding: {embed_time - rag_start:.2f}s, search: {rag_end - embed_time:.2f}s)")
            
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
                model="gpt-4.1-mini",
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
