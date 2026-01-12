from openai import OpenAI
from dotenv import load_dotenv
import asyncio
import logging
import time

load_dotenv()

logger = logging.getLogger(__name__)
client = OpenAI()

prompt = """
You are Patient Bot, a warm, supportive, and safety-focused assistant designed to help patients living with atrial fibrillation (AFib) or other heart rhythm issues.

Responsibilities:

Always use plain, simple language that heart patients and their families can easily understand. Avoid complicated medical terms.

Provide general education about heart health, lifestyle tips, and emotional support for people managing AFib.

Always format responses neatly with new lines, bullet points, or bold text for readability.

Include a clear disclaimer in every answer:
"I’m not a doctor, and this is not medical advice. For personal guidance, please talk to a qualified healthcare professional."

Communication Style:

Keep a warm, calm, and reassuring tone.

Be supportive and empathetic, acknowledging that living with AFib can feel stressful or confusing.

Use short paragraphs and bullet points for clarity.

Highlight key safety reminders, like when to seek urgent medical care (e.g., chest pain, severe shortness of breath, fainting).

Boundaries & Safety Rules:

Never give a diagnosis, prescribe medications, or suggest treatment plans.

If asked about drugs, dosages, or procedures (like ablation, blood thinners, or pacemakers), explain in simple terms what they are generally used for—but remind the patient to speak with their cardiologist.

Encourage safe, everyday lifestyle tips, such as:

Heart-healthy diet basics

Gentle physical activity (if cleared by their doctor)

Stress management and sleep hygiene

Tracking symptoms and sharing them with their doctor

If a user asks about symptoms (e.g., dizziness, palpitations, chest discomfort), give supportive guidance but always encourage urgent professional care if symptoms are severe or sudden.

If a question seems unsafe or harmful, respond with general reassurance and direct them to seek professional medical help.

Example Response Style (for AFib context):

Question: “Is catheter ablation safe for AFib?”

Answer:

Catheter ablation is a medical procedure doctors sometimes use to help people with atrial fibrillation.

It works by targeting the parts of the heart that may be causing the irregular rhythm.

Some patients find it helps reduce symptoms, but whether it’s safe or right for you depends on your health, age, and other factors.

Important: Only a cardiologist who knows your medical history can tell you if this procedure is a good option.

Friendly tip: Write down your questions and concerns before your next heart appointment so you feel confident discussing them.

Disclaimer:
I’m not a doctor, and this is not medical advice. For personal guidance, please talk to a qualified healthcare professional.



"""

async def patient_response(message, max_retries=3):
    """Patient response with retry logic"""
    # Retry logic for API failures
    for attempt in range(max_retries):
        try:
            # Create a streaming chat completion
            stream = client.chat.completions.create(
                model="gpt-4o-mini",   # choose the model
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": message}
                ],
                stream=True,
                timeout=30.0,  # Add timeout
                max_tokens=1000  # Limit response length
            )
            
            # Create an async generator
            async def generate():
                try:
                    for chunk in stream:
                        if chunk.choices and chunk.choices[0].delta.content is not None:
                            content = chunk.choices[0].delta.content
                            # Ensure we're yielding string data
                            if content:
                                yield content
                except Exception as e:
                    logger.error(f"Error in streaming chunk: {e}", exc_info=True)
                    yield "data: Sorry, I encountered an error processing your request.\n\n"
            
            # Return the generator itself, not the coroutine
            return generate()
            
        except Exception as e:
            logger.warning(f"Attempt {attempt + 1} failed: {e}")
            if attempt < max_retries - 1:
                # Exponential backoff
                wait_time = 2 ** attempt
                logger.info(f"Retrying in {wait_time} seconds...")
                await asyncio.sleep(wait_time)
            else:
                logger.error(f"All {max_retries} attempts failed")
                # Return a fallback response generator
                async def fallback_response():
                    yield "I'm experiencing technical difficulties right now. Please try again in a moment."
                return fallback_response()

async def patient_response_with_context(message, context_messages, max_retries=3):
    """Patient response with conversation context and retry logic"""
    # Build messages array with context
    messages = [{"role": "system", "content": prompt}]
    
    # Add context messages (last 2 messages + any long-term context)
    for ctx_msg in context_messages:
        messages.append({
            "role": ctx_msg["role"],
            "content": ctx_msg["content"]
        })
    
    # Add current message
    messages.append({"role": "user", "content": message})
    
    # Retry logic for API failures
    for attempt in range(max_retries):
        try:
            # Create a streaming chat completion
            stream = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                stream=True,
                timeout=30.0,  # Add timeout
                max_tokens=1000  # Limit response length
            )
            
            # Create an async generator
            async def generate():
                try:
                    for chunk in stream:
                        if chunk.choices and chunk.choices[0].delta.content is not None:
                            content = chunk.choices[0].delta.content
                            # Ensure we're yielding string data
                            if content:
                                yield content
                except Exception as e:
                    logger.error(f"Error in streaming chunk: {e}", exc_info=True)
                    yield "Sorry, I encountered an error processing your request."
            
            return generate()
            
        except Exception as e:
            logger.warning(f"Attempt {attempt + 1} failed: {e}")
            if attempt < max_retries - 1:
                # Exponential backoff
                wait_time = 2 ** attempt
                logger.info(f"Retrying in {wait_time} seconds...")
                await asyncio.sleep(wait_time)
            else:
                logger.error(f"All {max_retries} attempts failed")
                # Return a fallback response generator
                async def fallback_response():
                    yield "I'm experiencing technical difficulties right now. Please try again in a moment. If the problem persists, please contact support."
                return fallback_response()
