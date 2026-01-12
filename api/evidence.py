from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from typing import List, Optional, Dict, Any
from datetime import datetime
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import func
from database.database import get_db
from database.models import ResearchPaper, ResearchPaperScore, ResearchPaperKeyword, ResearchPaperComment, User
from utils.evidence_engine import get_evidence_with_details, get_all_categories, get_all_paper_types, get_files_with_pagination, get_paper_by_id, get_papers_count
from utils.evidence_cache import evidence_cache
from utils.auth_dependencies import get_current_user
from utils.validation import (
    ValidationMiddleware, SQLInjectionProtection, RateLimitValidation
)
from utils.query_optimizer import QueryOptimizer
from pydantic import BaseModel, Field, validator, ConfigDict
from typing import List, Optional, Dict, Any, Union
from config import settings
from slowapi import Limiter
from slowapi.util import get_remote_address
import logging

logger = logging.getLogger(__name__)

# Initialize rate limiter
limiter = Limiter(key_func=get_remote_address)

router = APIRouter(
    prefix="/api/evidence",
    tags=["evidence"],
    responses={404: {"description": "Not found"}},
)

class CategoryScoreFilter(BaseModel):
    min: Optional[int] = Field(None, ge=0, le=100, description="Minimum score for the category (0-100)")
    max: Optional[int] = Field(None, ge=0, le=100, description="Maximum score for the category (0-100)")

class PaginationParams(BaseModel):
    """Pagination parameters for list endpoints"""
    page: int = Field(1, ge=1, description="Page number (1-based)")
    page_size: int = Field(10, ge=1, le=100, description="Number of items per page")

    @validator('page_size')
    def validate_page_size(cls, v):
        if v > 100:
            raise ValueError("Page size cannot exceed 100")
        return v

class EvidenceFilter(BaseModel):
    # Basic Filters
    paper_types: Optional[List[str]] = Field(None, description="Filter by document types (research_journal, report, thesis, etc.)")
    start_date: Optional[datetime] = Field(None, description="Filter by start date (created_at)")
    end_date: Optional[datetime] = Field(None, description="Filter by end date (created_at)")
    file_name: Optional[str] = Field(None, description="Filter by full or partial filename")
    
    # Score-Based Filters
    min_total_score: Optional[int] = Field(None, ge=0, le=100, description="Minimum total score (0-100)")
    max_total_score: Optional[int] = Field(None, ge=0, le=100, description="Maximum total score (0-100)")
    min_confidence: Optional[int] = Field(None, ge=0, le=100, description="Minimum confidence score (0-100)")
    max_confidence: Optional[int] = Field(None, ge=0, le=100, description="Maximum confidence score (0-100)")
    category_scores: Optional[Dict[str, CategoryScoreFilter]] = Field(
        None, 
        description="Filter by category scores. Key is category name, value is {min: X, max: Y}"
    )
    
    # Content-Based Filters
    keywords: Optional[List[str]] = Field(None, description="Filter by one or more keywords")
    comments: Optional[List[str]] = Field(None, description="Filter papers containing specific comments")
    search_text: Optional[str] = Field(None, description="Full-text search across paper content")
    
    # Advanced Filters
    min_keywords: Optional[int] = Field(None, ge=0, description="Minimum number of keywords a paper must have")
    has_comments: Optional[bool] = Field(None, description="Filter papers that have/don't have comments")
    min_confidence_threshold: Optional[int] = Field(
        None, 
        ge=0, 
        le=100, 
        description="Filter by minimum confidence threshold (0-100)"
    )
    
    # Pagination
    skip: int = Field(0, ge=0, description="Number of records to skip for pagination")
    limit: int = Field(100, ge=1, le=1000, description="Maximum number of records to return")

@router.post("/search", response_model=List[Dict[str, Any]])
@limiter.limit(f"{settings.RATE_LIMIT * 2}/minute")
async def search_evidence(
    request: Request,
    filters: EvidenceFilter,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Search and filter research papers based on various criteria.
    
    This endpoint allows for complex filtering of research papers using multiple criteria
    including scores, categories, keywords, and more.
    """
    logger.info("Received search request with filters: %s", filters.dict(exclude_none=True))
    
    try:
        # Convert Pydantic model to dict and remove None values
        filter_dict = filters.dict(exclude_none=True)
        
        # Convert category scores to the format expected by the engine
        if 'category_scores' in filter_dict and filter_dict['category_scores']:
            filter_dict['category_scores'] = {
                k: v.dict(exclude_none=True) 
                for k, v in filters.category_scores.items()
                if v is not None
            }
        
        # Call the evidence engine to get filtered results
        results = get_evidence_with_details(db, **filter_dict)
        
        logger.info("Search completed successfully. Found %d results.", len(results))
        return results
        
    except SQLAlchemyError as e:
        error_msg = f"Database error during search: {str(e)}"
        logger.error(error_msg, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=error_msg
        )
    except ValueError as e:
        error_msg = f"Invalid input parameters: {str(e)}"
        logger.warning(error_msg)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_msg
        )
    except Exception as e:
        error_msg = f"Unexpected error during search: {str(e)}"
        logger.error(error_msg, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while processing your request"
        )

@router.get("/categories", response_model=List[str])
@limiter.limit(f"{settings.RATE_LIMIT * 3}/minute")
async def get_available_categories(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get a list of all available score categories.
    """
    try:
        categories = get_all_categories(db)
        
        if not categories:
            logger.warning("No categories found in the database")
            return []
            
        return categories
        
    except Exception as e:
        error_msg = f"Error while fetching categories: {str(e)}"
        logger.error(error_msg)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while fetching categories"
        )

@router.get("/paper-types", response_model=List[str])
@limiter.limit(f"{settings.RATE_LIMIT * 3}/minute")
async def get_available_paper_types(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get a list of all available paper types.
    """
    try:
        paper_types = get_all_paper_types(db)
        
        if not paper_types:
            logger.warning("No paper types found in the database")
            return []
            
        return paper_types
        
    except Exception as e:
        error_msg = f"Error while fetching paper types: {str(e)}"
        logger.error(error_msg)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while fetching paper types"
        )

class CommentResponse(BaseModel):
    """Response model for comments"""
    id: int
    comment: str
    is_penalty: bool = False
    model_config = ConfigDict(from_attributes=True)

class FileResponse(BaseModel):
    """Response model for file listing"""
    id: int
    file_name: str
    paper_type: Optional[str] = None  # Make it explicitly optional
    total_score: int
    confidence: int
    created_at: datetime
    updated_at: datetime
    keywords: List[str] = Field(default_factory=list)
    comments: List[CommentResponse] = Field(default_factory=list)
    
    model_config = ConfigDict(from_attributes=True)

class PaginatedFilesResponse(BaseModel):
    """Response model for paginated files"""
    items: List[FileResponse]
    total: int
    page: int
    page_size: int
    total_pages: int

@router.get("/files", response_model=PaginatedFilesResponse)
@limiter.limit(f"{settings.RATE_LIMIT * 2}/minute")
async def get_all_files(
    request: Request,
    pagination: PaginationParams = Depends(),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get all files with pagination.
    
    Returns a paginated list of all research papers in the database.
    """
    try:
        result = get_files_with_pagination(db, pagination.page, pagination.page_size)
        
        # Convert to response model
        response_items = []
        for item in result["items"]:
            response_items.append(FileResponse(**item))
        
        return PaginatedFilesResponse(
            items=response_items,
            total=result["total"],
            page=result["page"],
            page_size=result["page_size"],
            total_pages=result["total_pages"]
        )
        
    except Exception as e:
        error_msg = f"Error while fetching files: {str(e)}"
        logger.error(error_msg)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while fetching files" 
        )

@router.get("/cache/stats")
@limiter.limit(f"{settings.RATE_LIMIT * 3}/minute")
async def get_cache_stats(
    request: Request,
    current_user: User = Depends(get_current_user)
):
    """
    Get cache statistics (admin only).
    """
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    
    try:
        stats = evidence_cache.get_cache_stats()
        return stats
        
    except Exception as e:
        error_msg = f"Error getting cache stats: {str(e)}"
        logger.error(error_msg)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get cache statistics"
        )

@router.post("/cache/invalidate")
@limiter.limit(f"{settings.RATE_LIMIT}/minute")
async def invalidate_cache(
    request: Request,
    cache_type: Optional[str] = Query(None, description="Type of cache to invalidate (search, categories, paper_types, files, paper, count)"),
    current_user: User = Depends(get_current_user)
):
    """
    Invalidate cache (admin only).
    
    Args:
        cache_type: Specific cache type to invalidate, or None to invalidate all
    """
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    
    try:
        if cache_type:
            if cache_type not in evidence_cache.KEY_PREFIXES:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid cache type. Valid types: {list(evidence_cache.KEY_PREFIXES.keys())}"
                )
            
            success = evidence_cache.invalidate(cache_type)
            message = f"Cache invalidated for type: {cache_type}"
        else:
            success = evidence_cache.invalidate_all()
            message = "All evidence cache invalidated"
        
        logger.info(f"Cache invalidation requested by {current_user.email}: {message}")
        
        return {
            "success": success,
            "message": message,
            "invalidated_by": current_user.email,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        error_msg = f"Error invalidating cache: {str(e)}"
        logger.error(error_msg)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to invalidate cache"
        )
