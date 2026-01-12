from typing import List, Optional, Dict, Any, Union
from datetime import datetime
from sqlalchemy.orm import Session, Query, joinedload
from sqlalchemy import and_, or_, func
from database.models import ResearchPaper, ResearchPaperScore, ResearchPaperKeyword, ResearchPaperComment
from utils.evidence_cache import cached_evidence_query, cached_count_query
from utils.performance_monitor import monitor_performance, log_database_query

def build_evidence_query(
    db: Session,
    # Basic Filters
    paper_types: Optional[List[str]] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    file_name: Optional[str] = None,
    
    # Score-Based Filters
    min_total_score: Optional[int] = None,
    max_total_score: Optional[int] = None,
    min_confidence: Optional[int] = None,
    max_confidence: Optional[int] = None,
    category_scores: Optional[Dict[str, Dict[str, int]]] = None,
    
    # Content-Based Filters
    keywords: Optional[List[str]] = None,
    comments: Optional[List[str]] = None,
    search_text: Optional[str] = None,
    
    # Advanced Filters
    min_keywords: Optional[int] = None,
    has_comments: Optional[bool] = None,
    min_confidence_threshold: Optional[int] = None,
    
    # Pagination
    skip: int = 0,
    limit: int = 100
) -> Query:
    """
    Build a query to filter research papers based on various criteria.
    
    Args:
        db: SQLAlchemy database session
        paper_types: List of paper types to include
        start_date: Filter papers created after this date
        end_date: Filter papers created before this date
        file_name: Filter by full or partial filename
        min_total_score: Minimum total score (0-100)
        max_total_score: Maximum total score (0-100)
        min_confidence: Minimum confidence score (0-100)
        max_confidence: Maximum confidence score (0-100)
        category_scores: Dict of category filters in format {
            'category_name': {'min': X, 'max': Y}
        }
        keywords: List of keywords to search for
        comments: List of comments to search for
        search_text: Full-text search across paper content
        min_keywords: Minimum number of keywords a paper must have
        has_comments: Filter papers that have/don't have comments
        min_confidence_threshold: Minimum confidence threshold (0-100)
        skip: Number of records to skip for pagination
        limit: Maximum number of records to return
        
    Returns:
        SQLAlchemy Query object with all filters applied
    """
    query = db.query(ResearchPaper)
    
    # Basic Filters
    if paper_types:
        query = query.filter(ResearchPaper.paper_type.in_(paper_types))
        
    if start_date:
        query = query.filter(ResearchPaper.created_at >= start_date)
        
    if end_date:
        query = query.filter(ResearchPaper.created_at <= end_date)
        
    if file_name:
        query = query.filter(ResearchPaper.file_name.ilike(f'%{file_name}%'))
    
    # Score-Based Filters
    if min_total_score is not None:
        query = query.filter(ResearchPaper.total_score >= min_total_score)
        
    if max_total_score is not None:
        query = query.filter(ResearchPaper.total_score <= max_total_score)
        
    if min_confidence is not None:
        query = query.filter(ResearchPaper.confidence >= min_confidence)
        
    if max_confidence is not None:
        query = query.filter(ResearchPaper.confidence <= max_confidence)
    
    # Category Scores
    if category_scores:
        for category, score_range in category_scores.items():
            subq = db.query(ResearchPaperScore.research_paper_id)
            subq = subq.filter(ResearchPaperScore.category == category)
            
            if 'min' in score_range:
                subq = subq.filter(ResearchPaperScore.score >= score_range['min'])
            if 'max' in score_range:
                subq = subq.filter(ResearchPaperScore.score <= score_range['max'])
                
            query = query.filter(ResearchPaper.id.in_(subq.subquery()))
    
    # Content-Based Filters
    if keywords:
        keyword_subq = db.query(ResearchPaperKeyword.research_paper_id)
        keyword_subq = keyword_subq.filter(ResearchPaperKeyword.keyword.in_(keywords))
        
        if min_keywords is not None:
            keyword_subq = keyword_subq.group_by(ResearchPaperKeyword.research_paper_id)
            keyword_subq = keyword_subq.having(func.count(ResearchPaperKeyword.keyword) >= min_keywords)
            
        query = query.filter(ResearchPaper.id.in_(keyword_subq.subquery()))
    
    if comments:
        comment_subq = db.query(ResearchPaperComment.research_paper_id)
        comment_conditions = [ResearchPaperComment.comment.ilike(f'%{comment}%') for comment in comments]
        comment_subq = comment_subq.filter(or_(*comment_conditions))
        query = query.filter(ResearchPaper.id.in_(comment_subq.subquery()))
    
    # Advanced Filters
    if has_comments is not None:
        comment_count_subq = db.query(ResearchPaperComment.research_paper_id)
        if has_comments:
            query = query.filter(ResearchPaper.id.in_(comment_count_subq.subquery()))
        else:
            query = query.filter(~ResearchPaper.id.in_(comment_count_subq.subquery()))
    
    if min_confidence_threshold is not None:
        query = query.filter(ResearchPaper.confidence >= min_confidence_threshold)
    
    # Order by most recent first
    query = query.order_by(ResearchPaper.created_at.desc())
    
    # Eager load relationships to prevent N+1 queries
    query = query.options(
        joinedload(ResearchPaper.scores),
        joinedload(ResearchPaper.keywords),
        joinedload(ResearchPaper.comments)
    )
    
    # Apply pagination
    return query.offset(skip).limit(limit)

@monitor_performance
@cached_evidence_query('search_results', ttl=1800)
def get_evidence_with_details(
    db: Session,
    **filters
) -> List[Dict[str, Any]]:
    """
    Get research papers with all related data based on filters.
    
    Args:
        db: SQLAlchemy database session
        **filters: Filter arguments to pass to build_evidence_query
        
    Returns:
        List of dictionaries containing paper data with related scores, keywords, and comments
    """
    query = build_evidence_query(db, **filters)
    papers = query.all()
    
    result = []
    for paper in papers:
        paper_data = {
            'id': paper.id,
            'file_name': paper.file_name,
            'total_score': paper.total_score,
            'confidence': paper.confidence,
            'paper_type': paper.paper_type,
            'created_at': paper.created_at.isoformat(),
            'scores': [],
            'keywords': [],
            'comments': []
        }
        
        # Add scores
        for score in paper.scores:
            paper_data['scores'].append({
                'category': score.category,
                'score': score.score,
                'rationale': score.rationale,
                'max_score': score.max_score
            })
            
        # Add keywords
        paper_data['keywords'] = [kw.keyword for kw in paper.keywords]
        
        # Add comments
        for comment in paper.comments:
            paper_data['comments'].append({
                'comment': comment.comment,
                'is_penalty': comment.is_penalty
            })
            
        result.append(paper_data)
    
    return result

@cached_evidence_query('paper_details', ttl=1800)
def get_paper_by_id(db: Session, paper_id: int) -> Optional[Dict[str, Any]]:
    """
    Get a single research paper with all details by ID.
    
    Args:
        db: SQLAlchemy database session
        paper_id: ID of paper to retrieve
        
    Returns:
        Dictionary containing paper data with related scores, keywords, and comments
    """
    # Use eager loading to prevent N+1 queries
    paper = (db.query(ResearchPaper)
               .options(
                   joinedload(ResearchPaper.scores),
                   joinedload(ResearchPaper.keywords),
                   joinedload(ResearchPaper.comments)
               )
               .filter(ResearchPaper.id == paper_id)
               .first())
    
    if not paper:
        return None
    
    paper_data = {
        'id': paper.id,
        'file_name': paper.file_name,
        'total_score': paper.total_score,
        'confidence': paper.confidence,
        'paper_type': paper.paper_type,
        'created_at': paper.created_at.isoformat(),
        'updated_at': paper.updated_at.isoformat(),
        'scores': [],
        'keywords': [],
        'comments': []
    }
    
    # Add scores (already loaded via joinedload)
    for score in paper.scores:
        paper_data['scores'].append({
            'category': score.category,
            'score': score.score,
            'rationale': score.rationale,
            'max_score': score.max_score
        })
        
    # Add keywords (already loaded via joinedload)
    paper_data['keywords'] = [kw.keyword for kw in paper.keywords]
    
    # Add comments (already loaded via joinedload)
    for comment in paper.comments:
        paper_data['comments'].append({
            'comment': comment.comment,
            'is_penalty': comment.is_penalty
        })
        
    return paper_data

@cached_count_query('count', ttl=300)
def get_papers_count(db: Session, **filters) -> int:
    """
    Get count of research papers matching filters.
    
    Args:
        db: SQLAlchemy database session
        **filters: Filter arguments to pass to build_evidence_query
        
    Returns:
        Count of matching papers
    """
    query = build_evidence_query(db, **filters)
    return query.count()

@cached_evidence_query('categories', ttl=3600)
def get_all_categories(db: Session) -> List[str]:
    """
    Get all available score categories.
    
    Args:
        db: SQLAlchemy database session
        
    Returns:
        List of category names
    """
    categories = db.query(ResearchPaperScore.category)\
                  .distinct()\
                  .all()
    return [str(c[0]) for c in categories if c[0] is not None]

@cached_evidence_query('paper_types', ttl=3600)
def get_all_paper_types(db: Session) -> List[str]:
    """
    Get all available paper types.
    
    Args:
        db: SQLAlchemy database session
        
    Returns:
        List of paper type names
    """
    paper_types = db.query(ResearchPaper.paper_type)\
                   .distinct()\
                   .all()
    return [str(t[0]) for t in paper_types if t[0] is not None]

@monitor_performance
@cached_evidence_query('files', ttl=600)
def get_files_with_pagination(
    db: Session,
    page: int = 1,
    page_size: int = 10
) -> Dict[str, Any]:
    """
    Get paginated list of all files.
    
    Args:
        db: SQLAlchemy database session
        page: Page number (1-based)
        page_size: Number of items per page
        
    Returns:
        Dictionary with items, total, page, page_size, total_pages
    """
    from sqlalchemy.orm import joinedload
    
    # Calculate pagination
    offset = (page - 1) * page_size
    
    # Use a single query with subquery for better performance
    # Get paginated results with relationships in one query
    files_query = (db.query(ResearchPaper)
                  .options(
                      joinedload(ResearchPaper.keywords),
                      joinedload(ResearchPaper.comments)
                  )
                  .order_by(ResearchPaper.created_at.desc())
                  .offset(offset)
                  .limit(page_size))
    
    # Execute query
    files = files_query.all()
    
    # Get total count more efficiently using the same base query
    total_query = db.query(func.count(ResearchPaper.id))
    total = total_query.scalar()
    
    # Calculate total pages
    total_pages = (total + page_size - 1) // page_size
    
    # Format the response
    items = []
    for file in files:
        file_dict = {
            'id': file.id,
            'file_name': file.file_name,
            'paper_type': file.paper_type,
            'total_score': file.total_score,
            'confidence': file.confidence,
            'created_at': file.created_at,
            'updated_at': file.updated_at,
            'keywords': [kw.keyword for kw in file.keywords] if file.keywords else [],
            'comments': [
                {
                    'id': c.id,
                    'comment': c.comment,
                    'is_penalty': c.is_penalty
                } for c in file.comments
            ] if file.comments else []
        }
        items.append(file_dict)
    
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages
    }
