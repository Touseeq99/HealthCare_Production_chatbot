from datetime import datetime
from typing import Dict, Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

# Import database and models
from database.database import get_db
from database.models import User, Article
from api.auth import get_current_user
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
    author_id: int = None
    author: str = None
    
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
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
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
        articles = db.query(Article).filter(Article.status == "published").all()
        return [
            {
                "id": article.id,
                "title": article.title,
                "content": article.content,
                "created_at": article.created_at
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
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
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
        article = db.query(Article).filter(
            Article.id == article_id,
            Article.status == "published"
        ).first()
        
        if not article:
            raise HTTPException(
                status_code=404,
                detail="Article not found"
            )
        
        return {
            "id": article.id,
            "title": article.title,
            "content": article.content,
            "created_at": article.created_at
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
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
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
        articles = db.query(Article).all()
        return [
            {
                "id": article.id,
                "title": article.title,
                "content": article.content,
                "author_id": article.author_id,
                "created_at": article.created_at,
                "status": article.status
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
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
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
        author_id = current_user.id
        
        # Create article with all required fields
        article = Article(
            title=article_data.title,
            content=article_data.content,
            author_id=author_id,
            status="published"
        )
        
        try:
            db.add(article)
            db.commit()
            db.refresh(article)
            
            return {
                "id": article.id,
                "title": article.title,
                "content": article.content,
                "author": current_user.name,
                "date": article.created_at,
                "status": article.status
            }
            
        except Exception as db_error:
            db.rollback()
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