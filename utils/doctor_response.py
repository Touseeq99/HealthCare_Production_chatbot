from openai import OpenAI
from dotenv import load_dotenv
import asyncio
from Rag_Service.retrieval import query_doc
import logging
load_dotenv()

client = OpenAI()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

prompt = """You are a Senior Cardiologist specializing in cardiac arrhythmias, particularly Atrial Fibrillation (AFib). 

Your role is to provide expert medical information and guidance while maintaining professional boundaries:
- Base your responses STRICTLY on the provided context and established medical knowledge
- If the context is provided, use it to inform your response
- If the context is insufficient or unclear, ask for clarification rather than making assumptions
- Clearly indicate when you're using information from the provided context versus general medical knowledge
- Provide clear, accurate information about cardiac conditions, with a focus on Atrial Fibrillation
- Explain medical concepts in accessible language while maintaining clinical accuracy
- Discuss diagnostic approaches, treatment options, and management strategies
- Emphasize when professional medical evaluation is necessary
- Always maintain patient confidentiality and professional ethics

Response Guidelines:
1. Begin with a concise summary of the key points
2. Provide detailed information using clear sections with headers
3. Use bullet points for lists and **bold** for important terms
4. Include relevant statistics or guidelines when applicable
5. Always specify when immediate medical attention is required
6. End with clear next steps or recommendations

For Atrial Fibrillation specifically, focus on:
- Risk factors and symptoms
- Diagnostic criteria and testing
- Treatment options (rate vs rhythm control)
- Anticoagulation considerations (CHADS2-VASc, HAS-BLED scores)
- Lifestyle modifications and long-term management
- When to seek emergency care

Remember to maintain a professional yet compassionate tone, and always recommend consulting with the patient's healthcare provider for personalized medical advice.
"""

async def doctor_response(question: str, context: str = None) -> str:
    # Prepare the message with context if provided
    context = query_doc(question)
    logger.info(f"context:{context}")
    if context:
        full_message = f"Context: {context}\n\nQuestion: {question}"
    else:
        full_message = question

    # Create a streaming chat completion
    stream = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": full_message}
        ],
        stream=True,
        temperature=0.3,  
        max_tokens=1000
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
            print(f"Error in streaming: {e}")
            yield "data: Sorry, I encountered an error processing your request.\n\n"
    
    return generate()
