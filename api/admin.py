from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

# Import database and models
from database.database import get_db
from database.models import User, ChatSession
from database.models import Article  # Import Article from the models module

router = APIRouter()

@router.get("/users", response_model=Dict[str, Any])
async def get_users(db: Session = Depends(get_db)) -> JSONResponse:
    try:
        total_users = db.query(User).count()
        active_patients = db.query(User).filter(User.role == "patient").count()
        active_doctors = db.query(User).filter(User.role == "doctor").count()
        chat_sessions = db.query(ChatSession).count()
        
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
        return JSONResponse(
            status_code=500,
            content={"error": "Internal server error", "details": str(e)}
        )



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

# Article API
@router.get("/articles", response_model=List[Dict[str, Any]])
async def get_articles(db: Session = Depends(get_db)):
    try:
        articles = db.query(Article).filter(Article.status == "published").all()
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

@router.post("/articles", response_model=Dict[str, Any], status_code=201)
async def create_article(article_data: ArticleBase, db: Session = Depends(get_db)):
    try:
        print(f"Received article data: {article_data}")
        

        # Set default admin ID (replace 1 with your actual admin user ID)
        admin_id = 1
        author_id = admin_id
        
        # Verify admin user exists
        admin_user = db.query(User).filter(User.id == admin_id).first()
        if not admin_user:
            raise HTTPException(
                status_code=400,
                detail={"error": "Default admin user not found"}
            )

        # Create article with all required fields
        article = Article(
            title=article_data.title,
            content=article_data.content,
            author_id=author_id,
            status="published"
        )
        print(f"Created article object: {article}")
        
        try:
            db.add(article)
            db.commit()
            db.refresh(article)
            print(f"Article created successfully: {article.id}")
            
            return {
                "id": article.id,
                "title": article.title,
                "content": article.content,
                "author": "Admin",
                "date": article.created_at,
                "status": article.status
            }
            
        except Exception as db_error:
            db.rollback()
            print(f"Database error: {str(db_error)}")
            raise HTTPException(
                status_code=500,
                detail={
                    "error": "Database operation failed",
                    "details": str(db_error)
                }
            )
            
    except HTTPException as he:
        print(f"HTTP Exception: {he.detail}")
        raise he
        
    except Exception as e:
        print(f"Unexpected error: {str(e)}")
        print(f"Error type: {type(e).__name__}")
        import traceback
        traceback.print_exc()
        
        raise HTTPException(
            status_code=500,
            detail={
                "error": "Internal server error",
                "type": type(e).__name__,
                "details": str(e)
            }
        )

    
