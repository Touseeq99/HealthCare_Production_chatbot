from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from utils.doctor_response import doctor_response
from database.models import User
from utils.auth_dependencies import get_current_user
from config import settings
from slowapi import Limiter
from slowapi.util import get_remote_address
import json

class Message(BaseModel):
    message: str

# Initialize rate limiter
limiter = Limiter(key_func=get_remote_address)

router = APIRouter()

@router.post("/doctor/stream")
@limiter.limit(f"{settings.RATE_LIMIT * 3}/minute")
async def stream_response(
    request: Request,
    message: Message,
    current_user: User = Depends(get_current_user)
):
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
