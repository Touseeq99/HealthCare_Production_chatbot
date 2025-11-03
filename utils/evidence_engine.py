from typing import List, Optional, Dict, Any, Union
from datetime import datetime
from sqlalchemy.orm import Session, Query
from sqlalchemy import and_, or_, func
from database.models import ResearchPaper, ResearchPaperScore, ResearchPaperKeyword, ResearchPaperComment

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
    
    # Apply pagination
    return query.offset(skip).limit(limit)

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
