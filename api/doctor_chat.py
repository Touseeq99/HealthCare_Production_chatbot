from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from utils.doctor_response import doctor_response
import json

class Message(BaseModel):
    message: str

router = APIRouter()

@router.post("/doctor/stream")
async def stream_response(message: Message):
    try:
        # Get the async generator
        stream = await doctor_response(message.message)
        
        # Create the streaming response
        return StreamingResponse(
            content=stream,
            media_type="text/event-stream",
            headers={
                'Cache-Control': 'no-cache',
                'Connection': 'keep-alive',
                'X-Accel-Buffering': 'no',
                'Content-Type': 'text/event-stream',
                'Transfer-Encoding': 'chunked'
            }
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
