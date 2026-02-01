from openai import AsyncOpenAI
from dotenv import load_dotenv
import asyncio
import logging
import time

load_dotenv()

logger = logging.getLogger(__name__)
client = AsyncOpenAI()

prompt = """
You are Patient Bot, a warm, supportive, and safety-focused assistant designed to help patients living with atrial fibrillation (AFib) or other heart rhythm issues.

Responsibilities:
1. Use plain, simple language for patients/families.
2. Provide education, lifestyle tips, and emotional support.
3. Neatly format with bullet points and bold text.
4. MANDATORY DISCLAIMER: "I’m not a doctor, and this is not medical advice. For personal guidance, please talk to a qualified healthcare professional."

Style: Reassuring, empathetic, calm.
Safety: Highlight when to seek urgent care (chest pain, shortness of breath).
Boundaries: No diagnosis, no prescriptions. Explain procedures/drugs generally.
"""

async def patient_response(message, max_retries=3):
    """Patient response with retry logic and async streaming"""
    for attempt in range(max_retries):
        try:
            stream = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": message}
                ],
                stream=True,
                timeout=30.0,
                max_tokens=1000
            )
            
            async def generate():
                try:
                    async for chunk in stream:
                        if chunk.choices and chunk.choices[0].delta.content:
                            yield chunk.choices[0].delta.content
                except Exception as e:
                    logger.error(f"Error in streaming chunk: {e}")
                    yield "Sorry, I encountered an error."
            
            return generate()
            
        except Exception as e:
            logger.warning(f"Attempt {attempt + 1} failed: {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)
            else:
                async def fallback_response():
                    yield "I'm experiencing technical difficulties. Please try again later."
                return fallback_response()

async def patient_response_with_context(message, context_messages, max_retries=3):
    """Patient response with conversation context and async logic"""
    messages = [{"role": "system", "content": prompt}]
    
    # Limit context to last 5 messages for speed
    for ctx_msg in context_messages[-5:]:
        messages.append({"role": ctx_msg["role"], "content": ctx_msg["content"]})
    
    messages.append({"role": "user", "content": message})
    
    for attempt in range(max_retries):
        try:
            stream = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                stream=True,
                timeout=30.0,
                max_tokens=1000
            )
            
            async def generate():
                try:
                    async for chunk in stream:
                        if chunk.choices and chunk.choices[0].delta.content:
                            yield chunk.choices[0].delta.content
                except Exception as e:
                    logger.error(f"Error in streaming chunk: {e}")
                    yield "Sorry, I encountered an error."
            
            return generate()
            
        except Exception as e:
            logger.warning(f"Attempt {attempt + 1} failed: {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)
            else:
                async def fallback_response():
                    yield "I'm having trouble connecting right now."
                return fallback_response()
