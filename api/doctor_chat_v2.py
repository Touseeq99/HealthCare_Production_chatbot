from fastapi import APIRouter, Request, Depends, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
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
from utils.error_handler import (
    AppException, AuthorizationError, NotFoundError, 
    DatabaseError, ExternalServiceError
)
from utils.logger import get_request_id
from typing import Optional, Any
import time

logger = logging.getLogger(__name__)

# Legacy models
class SessionResponse(BaseModel):
    session_id: int
    session_name: str
    message_count: int
    created_at: str
    last_message_at: Optional[str] = None

# Initialize rate limiter
limiter = Limiter(key_func=get_remote_address)
router = APIRouter()

@router.post("/doctor/stream")
@limiter.limit(f"{settings.RATE_LIMIT * 3}/minute")
async def stream_response(
    request: Request,
    message: MessageRequest,
    current_user: Any = Depends(get_current_user),
    memory: MemoryManager = Depends(get_memory_manager)
):
    """Streaming chat response for doctors with RAG context"""
    try:
        # Enhanced validation
        await ValidationMiddleware.validate_request_size(request, 2)
        await ValidationMiddleware.validate_content_type(request, ["application/json"])
        
        # SQL injection protection
        SQLInjectionProtection.validate_input_safety(message.message)
        
        # Create or get session
        session = memory.create_or_get_session(
            user_id=current_user.id,
            session_id=message.session_id,
            session_type='doctor'
        )
        
        # Save user message to memory
        memory.add_message(
            session_id=session['id'],
            user_id=current_user.id,
            content=message.message,
            role='user'
        )
        
        # Get context for LLM
        context = memory.get_context_for_llm(
            session_id=session['id'],
            include_long_term=True,
            long_term_limit=3
        )
        
        start_time = time.time()
        from utils.doctor_response import doctor_response_with_context
        
        # Get the async generator
        try:
            stream = await doctor_response_with_context(message.message, context)
        except Exception as e:
            logger.error(f"LLM Connection failed: {str(e)}")
            raise ExternalServiceError("OpenAI", str(e))
        
        user_id = current_user.id
        session_id = session['id']
        assistant_response = ""
        
        async def generate_with_memory():
            nonlocal assistant_response
            try:
                async for chunk in stream:
                    if chunk:
                        assistant_response += chunk
                        yield chunk
            except Exception as e:
                logger.error(f"Streaming error: {e}", extra={"request_id": get_request_id()})
                yield "data: [ERROR] Sorry, I encountered a connection issue. Please try again.\n\n"
            finally:
                total_duration = time.time() - start_time
                logger.info(f"Stream duration: {total_duration:.2f}s")
                
                if assistant_response.strip():
                    try:
                        memory.add_message(
                            session_id=session_id,
                            user_id=user_id,
                            content=assistant_response,
                            role='assistant'
                        )
                    except Exception as save_err:
                        logger.error(f"Failed to save assistant response: {save_err}")
        
        return StreamingResponse(
            content=generate_with_memory(),
            media_type="text/event-stream",
            headers={
                'Cache-Control': 'no-cache',
                'X-Session-ID': str(session['id'])
            }
        )
    except AppException:
        raise
    except Exception as e:
        logger.error(f"Fatal error in stream_response: {str(e)}", exc_info=True)
        raise DatabaseError("Failed to process chat request")

@router.post("/doctor/sessions", response_model=SessionResponse)
async def create_session(
    session_data: SessionCreateRequest,
    current_user: Any = Depends(get_current_user),
    memory: MemoryManager = Depends(get_memory_manager)
):
    """Create a new chat session"""
    try:
        session = memory.create_or_get_session(
            user_id=current_user.id,
            session_type='doctor'
        )
        
        if session_data.session_name:
            memory.long_term.update_session_name(session['id'], session_data.session_name)
        
        return SessionResponse(
            session_id=session['id'],
            session_name=session['session_name'],
            message_count=session['message_count'],
            created_at=session['created_at'],
            last_message_at=session['last_message_at']
        )
    except Exception as e:
        logger.error(f"Error creating session: {str(e)}")
        raise DatabaseError("Failed to create chat session")

@router.get("/doctor/sessions")
async def get_sessions(
    current_user: Any = Depends(get_current_user),
    memory: MemoryManager = Depends(get_memory_manager)
):
    """Get all user sessions"""
    try:
        sessions = memory.get_user_sessions(current_user.id)
        return {"sessions": sessions}
    except Exception as e:
        logger.error(f"Error fetching sessions: {str(e)}")
        raise DatabaseError("Failed to retrieve chat history")

@router.get("/doctor/sessions/{session_id}/history")
async def get_session_history(
    session_id: int,
    limit: int = 50,
    current_user: Any = Depends(get_current_user),
    memory: MemoryManager = Depends(get_memory_manager)
):
    """Get session message history"""
    # Verify ownership
    session = memory.get_session(session_id, current_user.id)
    if not session:
        raise AuthorizationError("Session not found or access denied")
        
    try:
        history = memory.get_session_history(session_id, limit)
        return {"session_id": session_id, "messages": history}
    except Exception as e:
        logger.error(f"Error fetching history: {str(e)}")
        raise DatabaseError("Failed to retrieve session messages")

@router.put("/doctor/sessions/{session_id}")
async def update_session(
    session_id: int,
    session_data: SessionCreateRequest,
    current_user: Any = Depends(get_current_user),
    memory: MemoryManager = Depends(get_memory_manager)
):
    """Update session name"""
    session = memory.get_session(session_id, current_user.id)
    if not session:
        raise NotFoundError("Session")
    
    try:
        if session_data.session_name:
            memory.long_term.update_session_name(session_id, session_data.session_name)
        
        updated_session = memory.get_session(session_id, current_user.id)
        return SessionResponse(
            session_id=updated_session['id'],
            session_name=updated_session['session_name'],
            message_count=updated_session['message_count'],
            created_at=updated_session['created_at'],
            last_message_at=updated_session['last_message_at']
        )
    except Exception as e:
        logger.error(f"Error updating session: {str(e)}")
        raise DatabaseError("Failed to update session name")

@router.delete("/doctor/sessions/{session_id}")
async def delete_session(
    session_id: int,
    current_user: Any = Depends(get_current_user),
    memory: MemoryManager = Depends(get_memory_manager)
):
    """Delete a session"""
    try:
        success = memory.delete_session(session_id, current_user.id)
        if not success:
            raise NotFoundError("Session")
        return {"message": "Session deleted successfully"}
    except AppException:
        raise
    except Exception as e:
        logger.error(f"Error deleting session: {str(e)}")
        raise DatabaseError("Failed to delete session")

@router.get("/doctor/sessions/{session_id}/stats")
async def get_session_stats(
    session_id: int,
    current_user: Any = Depends(get_current_user),
    memory: MemoryManager = Depends(get_memory_manager)
):
    """Get session statistics"""
    stats = memory.get_session_stats(session_id, current_user.id)
    if not stats:
        raise NotFoundError("Session")
    return stats
