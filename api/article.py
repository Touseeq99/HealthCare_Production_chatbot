from datetime import datetime
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

class PatientArticleResponse(BaseModel):
    id: int
    title: str
    content: str
    created_at: datetime
     
    class Config:
        from_attributes = True

# Patient accessible endpoints
@router.get("/articles", response_model=List[PatientArticleResponse])
@limiter.limit(f"{settings.RATE_LIMIT * 2}/minute")
async def get_articles_for_patients(
    request: Request,
    current_user: Any = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_client)
):
    """
    Get all published articles for patients and doctors
    """
    # Check if user is patient or doctor
    if current_user.role not in ["patient", "doctor"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Patient or Doctor access required"
        )
    
    try:
        response = supabase.table('articles').select('*').eq('status', 'published').execute()
        articles = response.data or []
        return [
            {
                "id": article['id'],
                "title": article['title'],
                "content": article['content'],
                "created_at": article['created_at']
            }
            for article in articles
        ]
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={"error": "Internal server error", "details": str(e)}
        )

@router.get("/articles/{article_id}", response_model=PatientArticleResponse)
@limiter.limit(f"{settings.RATE_LIMIT * 2}/minute")
async def get_article_by_id(
    request: Request,
    article_id: int,
    current_user: Any = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_client)
):
    """
    Get a specific article by ID for patients and doctors
    """
    # Check if user is patient or doctor
    if current_user.role not in ["patient", "doctor"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Patient or Doctor access required"
        )
    
    try:
        response = supabase.table('articles').select('*').eq('id', article_id).eq('status', 'published').execute()
        
        if not response.data:
            raise HTTPException(
                status_code=404,
                detail="Article not found"
            )
        
        article = response.data[0]
        return {
            "id": article['id'],
            "title": article['title'],
            "content": article['content'],
            "created_at": article['created_at']
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={"error": "Internal server error", "details": str(e)}
        )

# Admin endpoints (keeping existing functionality)
@router.get("/admin/articles", response_model=List[Dict[str, Any]])
@limiter.limit(f"{settings.RATE_LIMIT * 2}/minute")
async def get_articles_admin(
    request: Request,
    current_user: Any = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_client)
):
    """
    Get all articles (admin only) - includes draft articles
    """
    # Check if user is admin
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    try:
        response = supabase.table('articles').select('*').execute()
        articles = response.data or []
        return [
            {
                "id": article['id'],
                "title": article['title'],
                "content": article['content'],
                "author_id": article['author_id'],
                "created_at": article['created_at'],
                "status": article['status']
            }
            for article in articles
        ]
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={"error": "Internal server error", "details": str(e)}
        )

@router.post("/admin/articles", response_model=Dict[str, Any], status_code=201)
@limiter.limit(f"{settings.RATE_LIMIT}/minute")
async def create_article(
    request: Request,
    article_data: ArticleBase, 
    current_user: Any = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_client)
):
    """
    Create new article (admin only)
    """
    # Check if user is admin
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    try:
        # Use current admin user as author
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
        
        try:
            response = supabase.table('articles').insert(article_insert).execute()
            if not response.data:
                raise Exception("Failed to create article")
            
            article = response.data[0]
            
            return {
                "id": article['id'],
                "title": article['title'],
                "content": article['content'],
                "author": getattr(current_user, 'name', 'Admin'),
                "date": article['created_at'],
                "status": article['status']
            }
            
        except Exception as db_error:
            raise HTTPException(
                status_code=500,
                detail={
                    "error": "Database operation failed",
                    "details": str(db_error)
                }
            )
            
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "Internal server error",
                "type": type(e).__name__,
                "details": str(e)
            }
        )