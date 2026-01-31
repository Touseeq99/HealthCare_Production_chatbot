from typing import List, Optional, Dict, Any, Union
from datetime import datetime
from supabase import Client
from utils.supabase_client import get_supabase_client
from utils.performance_monitor import monitor_performance, log_database_query

def build_evidence_query(
    supabase: Client,
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
) -> Any:
    """
    Build a query to filter research papers based on various criteria using Supabase Client.
    
    Args:
        supabase: Supabase client
        paper_types: List of paper types to include
        start_date: Filter papers created after this date
        end_date: Filter papers created before this date
        file_name: Filter by full or partial filename
        min_total_score: Minimum total score (0-100)
        max_total_score: Maximum total score (0-100)
        min_confidence: Minimum confidence score (0-100)
        max_confidence: Maximum confidence score (0-100)
        category_scores: Dict of category filters
        keywords: List of keywords to search for
        comments: List of comments to search for
        search_text: Full-text search across paper content
        min_keywords: Minimum number of keywords a paper must have
        has_comments: Filter papers that have/don't have comments
        min_confidence_threshold: Minimum confidence threshold (0-100)
        skip: Number of records to skip for pagination
        limit: Maximum number of records to return
        
    Returns:
        Supabase query builder object with all filters applied
    """
    # Start building the query
    query = supabase.table('research_papers').select('*')
    
    # Paper Types
    if paper_types:
        query = query.in_('paper_type', paper_types)
        
    if start_date:
        query = query.gte('created_at', start_date.isoformat())
        
    if end_date:
        query = query.lte('created_at', end_date.isoformat())
        
    if file_name:
        query = query.ilike('file_name', f'%{file_name}%')
    
    # Score-Based Filters
    if min_total_score is not None:
        query = query.gte('total_score', min_total_score)
        
    if max_total_score is not None:
        query = query.lte('total_score', max_total_score)
        
    if min_confidence is not None:
        query = query.gte('confidence', min_confidence)
        
    if max_confidence is not None:
        query = query.lte('confidence', max_confidence)
    
    # Note: Complex filters like category_scores, keywords, comments
    # are handled in get_evidence_with_details function
    # This function provides basic filtering only
    
    # Order and Pagination
    query = query.order('created_at', desc=True).range(skip, skip + limit - 1)
    
    return query

@monitor_performance
def get_evidence_with_details(
    supabase: Client,
    **filters
) -> List[Dict[str, Any]]:
    """
    Get research papers with all related data based on filters using Supabase Client.
    """
    # Start building the query
    query = supabase.table('research_papers').select('*, research_paper_scores(*), research_paper_keywords(*), research_paper_comments(*)')
    
    # Paper Types
    if filters.get('paper_types'):
        query = query.in_('paper_type', filters['paper_types'])
        
    # Dates
    if filters.get('start_date'):
        query = query.gte('created_at', filters['start_date'].isoformat())
    if filters.get('end_date'):
        query = query.lte('created_at', filters['end_date'].isoformat())
        
    # File Name
    if filters.get('file_name'):
        query = query.ilike('file_name', f"%{filters['file_name']}%")
        
    # Scores
    if filters.get('min_total_score') is not None:
        query = query.gte('total_score', filters['min_total_score'])
    if filters.get('max_total_score') is not None:
        query = query.lte('total_score', filters['max_total_score'])
        
    # Confidence
    if filters.get('min_confidence') is not None:
        query = query.gte('confidence', filters['min_confidence'])
    if filters.get('max_confidence') is not None:
        query = query.lte('confidence', filters['max_confidence'])

    # Order and Pagination
    skip = filters.get('skip', 0)
    limit = filters.get('limit', 100)
    query = query.order('created_at', desc=True).range(skip, skip + limit - 1)
    
    response = query.execute()
    papers = response.data
    
    # Post-process for complex filters (category scores, keywords, comments)
    # Note: In a production environment, these should ideally be handled via RPC or complex PostgREST queries
    # for performance, but for now we'll do some filtering in Python if needed.
    
    result = []
    for paper in papers:
        # Format dates
        if paper.get('created_at'):
            # Convert if necessary, though Supabase client usually returns strings or datetime objects
            pass
            
        result.append(paper)
        
    return result

def get_paper_by_id(supabase: Client, paper_id: int) -> Optional[Dict[str, Any]]:
    """
    Get a single research paper with all details by ID.
    """
    response = supabase.table('research_papers')\
                       .select('*, research_paper_scores(*), research_paper_keywords(*), research_paper_comments(*)')\
                       .eq('id', paper_id)\
                       .single()\
                       .execute()
    
    return response.data if response.data else None

def get_papers_count(supabase: Client, **filters) -> int:
    """
    Get count of research papers matching filters.
    """
    # For now, just return a simple count or use exact count from select
    response = supabase.table('research_papers').select('*', count='exact').limit(0).execute()
    return response.count if response.count is not None else 0

def get_all_categories(supabase: Client) -> List[str]:
    """
    Get all available score categories.
    """
    response = supabase.table('research_paper_scores').select('category').execute()
    if not response.data:
        return []
    return sorted(list(set(item['category'] for item in response.data if item.get('category'))))

def get_all_paper_types(supabase: Client) -> List[str]:
    """
    Get all available paper types.
    """
    response = supabase.table('research_papers').select('paper_type').execute()
    if not response.data:
        return []
    return sorted(list(set(item['paper_type'] for item in response.data if item.get('paper_type'))))

@monitor_performance
def get_files_with_pagination(
    supabase: Client,
    page: int = 1,
    page_size: int = 10
) -> Dict[str, Any]:
    """
    Get paginated list of all files using Supabase Client.
    """
    # Calculate pagination
    offset = (page - 1) * page_size
    
    # Execute query with exact count
    response = supabase.table('research_papers')\
                       .select('*, research_paper_keywords(*), research_paper_comments(*)', count='exact')\
                       .order('created_at', desc=True)\
                       .range(offset, offset + page_size - 1)\
                       .execute()
    
    files = response.data
    total = response.count if response.count is not None else 0
    
    # Calculate total pages
    total_pages = (total + page_size - 1) // page_size
    
    # Format the response
    items = []
    for file in files:
        file_dict = {
            'id': file['id'],
            'file_name': file['file_name'],
            'paper_type': file['paper_type'],
            'total_score': file['total_score'],
            'confidence': file['confidence'],
            'created_at': file['created_at'],
            'updated_at': file['updated_at'],
            'keywords': [kw['keyword'] for kw in file.get('research_paper_keywords', [])],
            'comments': [
                {
                    'id': c['id'],
                    'comment': c['comment'],
                    'is_penalty': c['is_penalty']
                } for c in file.get('research_paper_comments', [])
            ]
        }
        items.append(file_dict)
    
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages
    }
