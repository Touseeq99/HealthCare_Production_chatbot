from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from supabase import Client

# Import Supabase client
from utils.supabase_client import get_supabase_client
from utils.auth_dependencies import get_current_user
from config import settings
from slowapi import Limiter
from slowapi.util import get_remote_address

# Initialize rate limiter
limiter = Limiter(key_func=get_remote_address)

router = APIRouter()

@router.get("/users", response_model=Dict[str, Any])
@limiter.limit(f"{settings.RATE_LIMIT * 2}/minute")
async def get_users(
    request: Request,
    current_user: Any = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_client)
) -> JSONResponse:
    # Check if user is admin
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    try:
        # Get counts using Supabase
        users_response = supabase.table('users').select('*', count='exact').execute()
        total_users = users_response.count or 0
        
        patients_response = supabase.table('users').select('*', count='exact').eq('role', 'patient').execute()
        active_patients = patients_response.count or 0
        
        doctors_response = supabase.table('users').select('*', count='exact').eq('role', 'doctor').execute()
        active_doctors = doctors_response.count or 0
        
        sessions_response = supabase.table('chat_sessions').select('*', count='exact').execute()
        chat_sessions = sessions_response.count or 0
        
        return JSONResponse(
            status_code=200,
            content={
                "totalUsers": total_users,
                "activePatients": active_patients,
                "activeDoctors": active_doctors,
                "chatSessions": chat_sessions
            }
        )
    except Exception as e:
        logger.error(f"Admin search error: {str(e)}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": "Internal server error"}
        )



# Pydantic models
class ArticleBase(BaseModel):
    title: str
    content: str
    author_id: Optional[str] = None
    author: Optional[str] = None
    
    class Config:
        extra = 'forbid'  # Reject any extra fields

class ArticleResponse(ArticleBase):
    id: int
    created_at: datetime
    status: str

    class Config:
        from_attributes = True

# Article API
@router.get("/articles", response_model=List[Dict[str, Any]])
@limiter.limit(f"{settings.RATE_LIMIT * 2}/minute")
async def get_articles(
    request: Request,
    current_user: Any = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_client)
):
    # Check if user is admin
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    try:
        response = supabase.table('articles').select('*').eq('status', 'published').execute()
        articles = response.data or []
        return [
            {
                "id": article['id'],
                "title": article['title'],
                "content": article['content'],
                "author_id": str(article['author_id']),
                "created_at": article['created_at'],
                "status": article['status']
            }
            for article in articles
        ]
    except Exception as e:
        logger.error(f"Admin fetch articles error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )

@router.post("/articles", response_model=Dict[str, Any], status_code=201)
@limiter.limit(f"{settings.RATE_LIMIT}/minute")
async def create_article(
    request: Request,
    article_data: ArticleBase, 
    current_user: Any = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_client)
):
    # Check if user is admin
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    try:
        print(f"Received article data: {article_data}")
        
        # Use the current admin user as the author
        author_id = str(current_user.id)
        
        # Create article with all required fields
        article_insert = {
            "title": article_data.title,
            "content": article_data.content,
            "author_id": author_id,
            "status": "published",
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat()
        }
        print(f"Creating article: {article_insert}")
        
        try:
            response = supabase.table('articles').insert(article_insert).execute()
            if not response.data:
                raise Exception("Failed to create article")
            
            article = response.data[0]
            print(f"Article created successfully: {article['id']}")
            
            return {
                "id": article['id'],
                "title": article['title'],
                "content": article['content'],
                "author": "Admin",
                "date": article['created_at'],
                "status": article['status']
            }
            
        except Exception as db_error:
            logger.error(f"Database error during article creation: {str(db_error)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Database operation failed"
            )
            
    except HTTPException as he:
        print(f"HTTP Exception: {he.detail}")
        raise he
        
    except Exception as e:
        logger.error(f"Unexpected admin error: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )

    
