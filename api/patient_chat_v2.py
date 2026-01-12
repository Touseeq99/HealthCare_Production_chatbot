from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from database.database import get_db
from database.models import User
from utils.auth_dependencies import get_current_user
from memory.memory_manager import get_memory_manager, MemoryManager
from config import settings
from slowapi import Limiter
from slowapi.util import get_remote_address
import logging
from utils.validation import (
    MessageRequest, SessionCreateRequest, ValidationMiddleware, 
    SQLInjectionProtection, RateLimitValidation
)

logger = logging.getLogger(__name__)

class SessionResponse(BaseModel):
    session_id: int
    session_name: str
    message_count: int
    created_at: str
    last_message_at: str = None

# Initialize rate limiter
limiter = Limiter(key_func=get_remote_address)

router = APIRouter()

@router.post("/patient/stream")
@limiter.limit(f"{settings.RATE_LIMIT * 3}/minute")
async def stream_response(
    request: Request,
    message: MessageRequest,
    current_user: User = Depends(get_current_user),
    memory: MemoryManager = Depends(get_memory_manager)
):
    try:
        # Enhanced validation
        await ValidationMiddleware.validate_request_size(request, 2)  # 2MB limit
        await ValidationMiddleware.validate_content_type(request, ["application/json"])
        # Temporarily disabled for debugging
        # await ValidationMiddleware.validate_user_agent(request)
        # await ValidationMiddleware.validate_ip_address(request)
        
        # SQL injection protection
        SQLInjectionProtection.validate_input_safety(message.message)
        
        # Rate limiting based on user role
        rate_config = RateLimitValidation.get_rate_limit_config("chat", current_user.role)
        # Note: This would need Redis integration for per-user tracking
        
        # Create or get session
        session = memory.create_or_get_session(
            user_id=current_user.id,
            session_id=message.session_id,
            session_type='patient'
        )
        
        # Save user message to memory
        memory.add_message(
            session_id=session.id,
            user_id=current_user.id,
            content=message.message,
            role='user'
        )
        
        # Get context for LLM (last 2 messages + some long-term context)
        try:
            context = memory.get_context_for_llm(
                session_id=session.id,
                include_long_term=True,
                long_term_limit=3
            )
        except Exception as context_error:
            logger.warning(f"Error getting context, proceeding without it: {context_error}")
            context = []
        
        # Import here to avoid circular imports
        from utils.patient_response import patient_response_with_context
        
        # Get the async generator with context
        try:
            stream = await patient_response_with_context(message.message, context)
        except Exception as stream_error:
            logger.error(f"Error creating stream: {stream_error}", exc_info=True)
            # Create a fallback stream
            async def fallback_stream():
                yield "I'm having trouble connecting right now. Please try again in a moment."
            stream = fallback_stream()
        
        # Capture IDs before streaming to avoid DetachedInstanceError
        user_id = current_user.id
        session_id = session.id
        
        # Track assistant response
        assistant_response = ""
        
        async def generate_with_memory():
            nonlocal assistant_response
            try:
                async for chunk in stream:
                    # chunk is already a string content from patient_response_with_context
                    if chunk:
                        assistant_response += chunk
                        yield chunk
                logger.info(f"Streaming completed. Final assistant response length: {len(assistant_response)}")
            except Exception as e:
                logger.error(f"Error in streaming: {e}", exc_info=True)
                error_msg = "I'm experiencing technical difficulties right now. Please try again in a moment."
                yield error_msg
                assistant_response = error_msg  # Save error message to memory for debugging
            finally:
                # Save assistant response to memory
                if assistant_response.strip():
                    try:
                        memory.add_message(
                            session_id=session_id,
                            user_id=user_id,
                            content=assistant_response,
                            role='assistant'
                        )
                        logger.info("Assistant response saved successfully")
                    except Exception as save_error:
                        logger.error(f"Error saving assistant response: {save_error}", exc_info=True)
        
        # Create the streaming response
        return StreamingResponse(
            content=generate_with_memory(),
            media_type="text/event-stream",
            headers={
                'Cache-Control': 'no-cache',
                'Connection': 'keep-alive',
                'X-Accel-Buffering': 'no',
                'Content-Type': 'text/event-stream',
                'Transfer-Encoding': 'chunked',
                'X-Session-ID': str(session.id)
            }
        )
    except Exception as e:
        logger.error(f"FATAL ERROR in stream_response: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/patient/sessions", response_model=SessionResponse)
async def create_session(
    session_data: SessionCreateRequest,
    current_user: User = Depends(get_current_user),
    memory: MemoryManager = Depends(get_memory_manager)
):
    """Create a new chat session"""
    try:
        session = memory.create_or_get_session(
            user_id=current_user.id,
            session_type='patient'
        )
        
        if session_data.session_name:
            memory.long_term.update_session_name(session.id, session_data.session_name)
        
        return SessionResponse(
            session_id=session.id,
            session_name=session.session_name,
            message_count=session.message_count,
            created_at=session.created_at.isoformat(),
            last_message_at=session.last_message_at.isoformat() if session.last_message_at else None
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/patient/sessions")
async def get_sessions(
    current_user: User = Depends(get_current_user),
    memory: MemoryManager = Depends(get_memory_manager)
):
    """Get all user sessions"""
    try:
        sessions = memory.get_user_sessions(current_user.id)
        return {"sessions": sessions}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/patient/sessions/{session_id}/history")
async def get_session_history(
    session_id: int,
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    memory: MemoryManager = Depends(get_memory_manager)
):
    """Get session message history"""
    try:
        history = memory.get_session_history(session_id, limit)
        return {"session_id": session_id, "messages": history}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/patient/sessions/{session_id}")
async def update_session(
    session_id: int,
    session_data: SessionCreateRequest,
    current_user: User = Depends(get_current_user),
    memory: MemoryManager = Depends(get_memory_manager)
):
    """Update session name"""
    try:
        # Verify session belongs to user
        session = memory.get_session(session_id, current_user.id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        # Update session name if provided
        if session_data.session_name:
            memory.long_term.update_session_name(session_id, session_data.session_name)
        
        # Get updated session info
        updated_session = memory.get_session(session_id, current_user.id)
        
        return SessionResponse(
            session_id=updated_session.id,
            session_name=updated_session.session_name,
            message_count=updated_session.message_count,
            created_at=updated_session.created_at.isoformat(),
            last_message_at=updated_session.last_message_at.isoformat() if updated_session.last_message_at else None
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/patient/sessions/{session_id}")
async def delete_session(
    session_id: int,
    current_user: User = Depends(get_current_user),
    memory: MemoryManager = Depends(get_memory_manager)
):
    """Delete a session"""
    try:
        success = memory.delete_session(session_id, current_user.id)
        if not success:
            raise HTTPException(status_code=404, detail="Session not found")
        return {"message": "Session deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/patient/sessions/{session_id}/stats")
async def get_session_stats(
    session_id: int,
    current_user: User = Depends(get_current_user),
    memory: MemoryManager = Depends(get_memory_manager)
):
    """Get session statistics"""
    try:
        stats = memory.get_session_stats(session_id, current_user.id)
        if not stats:
            raise HTTPException(status_code=404, detail="Session not found")
        return stats
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
