from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
import logging

from fastapi import APIRouter, Depends, status, Request, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from supabase import Client

from utils.supabase_client import get_supabase_client
from utils.auth_dependencies import get_current_user
from config import settings
from slowapi import Limiter
from slowapi.util import get_remote_address
from utils.error_handler import (
    AppException, AuthorizationError, NotFoundError, 
    DatabaseError, ValidationError
)
from utils.logger import log_admin_action, get_request_id

logger = logging.getLogger(__name__)
limiter = Limiter(key_func=get_remote_address)
router = APIRouter()

# ============== Pydantic Models ==============
class UserRoleUpdate(BaseModel):
    role: str  # patient, doctor, admin

class ArticleUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    status: Optional[str] = None  # published, draft

# ============== USER STATISTICS ==============
@router.get("/stats", response_model=Dict[str, Any])
@limiter.limit(f"{settings.RATE_LIMIT * 2}/minute")
async def get_stats(
    request: Request,
    current_user: Any = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_client)
) -> JSONResponse:
    """Get dashboard statistics (Admin only)"""
    if current_user.role != "admin":
        raise AuthorizationError("Admin access required")
    try:
        users_response = supabase.table('users').select('*', count='exact').execute()
        patients_response = supabase.table('users').select('*', count='exact').eq('role', 'patient').execute()
        doctors_response = supabase.table('users').select('*', count='exact').eq('role', 'doctor').execute()
        sessions_response = supabase.table('chat_sessions').select('*', count='exact').execute()
        
        return JSONResponse(status_code=200, content={
            "totalUsers": users_response.count or 0,
            "activePatients": patients_response.count or 0,
            "activeDoctors": doctors_response.count or 0,
            "chatSessions": sessions_response.count or 0
        })
    except Exception as e:
        logger.error(f"Admin stats error: {str(e)}")
        raise DatabaseError("Failed to retrieve system statistics")

# ============== LIST ALL USERS (with details) ==============
@router.get("/users", response_model=List[Dict[str, Any]])
@limiter.limit(f"{settings.RATE_LIMIT * 2}/minute")
async def list_all_users(
    request: Request,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    role_filter: Optional[str] = Query(None),
    current_user: Any = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_client)
):
    """List all users with pagination (Admin only)"""
    if current_user.role != "admin":
        raise AuthorizationError()
    try:
        offset = (page - 1) * limit
        query = supabase.table('users').select('id, email, name, role, created_at, updated_at')
        
        if role_filter:
            query = query.eq('role', role_filter)
        
        response = query.order('created_at', desc=True).range(offset, offset + limit - 1).execute()
        return response.data or []
    except Exception as e:
        logger.error(f"List users error: {str(e)}")
        raise DatabaseError("Failed to list users")

# ============== CHANGE USER ROLE ==============
@router.put("/users/{user_id}/role")
@limiter.limit(f"{settings.RATE_LIMIT}/minute")
async def change_user_role(
    request: Request,
    user_id: str,
    role_data: UserRoleUpdate,
    current_user: Any = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_client)
):
    """Change a user's role (Admin only)"""
    if current_user.role != "admin":
        raise AuthorizationError()
    
    allowed_roles = ["patient", "doctor", "admin"]
    if role_data.role not in allowed_roles:
        raise ValidationError(f"Invalid role. Must be one of: {allowed_roles}")
    
    # Prevent self-demotion
    if str(current_user.id) == user_id and role_data.role != "admin":
        raise ValidationError("Cannot demote yourself from admin")
    
    try:
        response = supabase.table('users').update({
            "role": role_data.role,
            "updated_at": datetime.utcnow().isoformat()
        }).eq('id', user_id).execute()
        
        if not response.data:
            raise NotFoundError("User")
        
        # AUDIT LOGGING
        log_admin_action(
            action="CHANGE_ROLE",
            admin_id=str(current_user.id),
            target=user_id,
            details={"new_role": role_data.role}
        )
        
        return {"message": f"User role updated to {role_data.role}", "user": response.data[0]}
    except AppException:
        raise
    except Exception as e:
        logger.error(f"Change role error: {str(e)}")
        raise DatabaseError("Failed to update user role")

# ============== VIEW CHAT SESSION LOGS ==============
@router.get("/sessions")
@limiter.limit(f"{settings.RATE_LIMIT * 2}/minute")
async def get_all_sessions(
    request: Request,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    user_id: Optional[str] = Query(None),
    session_type: Optional[str] = Query(None),
    current_user: Any = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_client)
):
    """Get all chat sessions with filters (Admin only)"""
    if current_user.role != "admin":
        raise AuthorizationError()
    try:
        offset = (page - 1) * limit
        query = supabase.table('chat_sessions').select('*')
        
        if user_id:
            query = query.eq('user_id', user_id)
        if session_type:
            query = query.eq('session_type', session_type)
        
        response = query.order('created_at', desc=True).range(offset, offset + limit - 1).execute()
        return {"sessions": response.data or [], "page": page, "limit": limit}
    except Exception as e:
        logger.error(f"Get sessions error: {str(e)}")
        raise DatabaseError("Failed to list sessions")

@router.get("/sessions/{session_id}/messages")
async def get_session_messages(
    request: Request,
    session_id: int,
    limit: int = Query(100, ge=1, le=500),
    current_user: Any = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_client)
):
    """Get all messages from a specific session (Admin only)"""
    if current_user.role != "admin":
        raise AuthorizationError()
    try:
        # Get messages
        messages_response = supabase.table('chat_messages')\
            .select('*')\
            .eq('session_id', session_id)\
            .order('created_at', desc=False)\
            .limit(limit)\
            .execute()
        
        return {"session_id": session_id, "messages": messages_response.data or []}
    except Exception as e:
        logger.error(f"Get session messages error: {str(e)}")
        raise DatabaseError("Failed to fetch messages")

# ============== ARTICLE MANAGEMENT ==============
@router.put("/articles/{article_id}")
async def update_article(
    request: Request,
    article_id: int,
    article_data: ArticleUpdate,
    current_user: Any = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_client)
):
    """Update an article (Admin only)"""
    if current_user.role != "admin":
        raise AuthorizationError()
    try:
        update_data = {"updated_at": datetime.utcnow().isoformat()}
        if article_data.title: update_data["title"] = article_data.title
        if article_data.content: update_data["content"] = article_data.content
        if article_data.status: update_data["status"] = article_data.status
        
        response = supabase.table('articles').update(update_data).eq('id', article_id).execute()
        if not response.data:
            raise NotFoundError("Article")
        
        log_admin_action("UPDATE_ARTICLE", str(current_user.id), str(article_id))
        return {"message": "Article updated successfully", "article": response.data[0]}
    except AppException:
        raise
    except Exception as e:
        logger.error(f"Update article error: {str(e)}")
        raise DatabaseError("Failed to update article")

@router.delete("/articles/{article_id}")
async def delete_article(
    request: Request,
    article_id: int,
    current_user: Any = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_client)
):
    """Delete an article (Admin only)"""
    if current_user.role != "admin":
        raise AuthorizationError()
    try:
        response = supabase.table('articles').delete().eq('id', article_id).execute()
        if not response.data:
            raise NotFoundError("Article")
        
        log_admin_action("DELETE_ARTICLE", str(current_user.id), str(article_id))
        return {"message": "Article deleted successfully"}
    except AppException:
        raise
    except Exception as e:
        logger.error(f"Delete article error: {str(e)}")
        raise DatabaseError("Failed to delete article")
