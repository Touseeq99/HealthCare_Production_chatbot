"""
Query optimization utilities for chat and evidence endpoints
"""
from typing import List, Dict, Any, Optional, Tuple
from sqlalchemy.orm import Session, joinedload, selectinload
from sqlalchemy import func, and_, or_, desc, asc, text
from datetime import datetime, timedelta
from database.models import (
    ChatSession, ChatMessage, User, ResearchPaper, 
    ResearchPaperScore, ResearchPaperKeyword, ResearchPaperComment
)
from utils.logger import logger

class QueryOptimizer:
    """Optimized database queries for better performance"""
    
    @staticmethod
    def get_user_sessions_optimized(
        db: Session, 
        user_id: int, 
        session_type: str = 'patient',
        page: int = 1,
        page_size: int = 20,
        status: str = 'active'
    ) -> Tuple[List[ChatSession], int]:
        """Get user sessions with optimized query"""
        
        # Use subquery for better performance
        subquery = db.query(
            ChatSession.id,
            ChatSession.message_count,
            ChatSession.last_message_at,
            ChatSession.created_at
        ).filter(
            ChatSession.user_id == user_id,
            ChatSession.session_type == session_type,
            ChatSession.status == status
        ).subquery()
        
        # Main query with pagination
        query = db.query(ChatSession).filter(
            ChatSession.id.in_(db.query(subquery.c.id))
        ).order_by(desc(ChatSession.last_message_at))
        
        # Get total count efficiently
        total_count = db.query(ChatSession).filter(
            ChatSession.user_id == user_id,
            ChatSession.session_type == session_type,
            ChatSession.status == status
        ).count()
        
        # Apply pagination
        offset = (page - 1) * page_size
        sessions = query.offset(offset).limit(page_size).all()
        
        return sessions, total_count
    
    @staticmethod
    def get_chat_messages_optimized(
        db: Session,
        session_id: int,
        page: int = 1,
        page_size: int = 50,
        message_type: Optional[str] = None
    ) -> Tuple[List[ChatMessage], int]:
        """Get chat messages with optimized query"""
        
        # Build filters
        filters = [ChatMessage.session_id == session_id]
        if message_type:
            filters.append(ChatMessage.message_type == message_type)
        
        # Use window function for efficient pagination
        query = db.query(ChatMessage).filter(*filters)
        
        # Get total count
        total_count = query.count()
        
        # Apply pagination with ordering
        messages = query.order_by(ChatMessage.created_at).offset(
            (page - 1) * page_size
        ).limit(page_size).all()
        
        return messages, total_count
    
    @staticmethod
    def search_research_papers_optimized(
        db: Session,
        filters: Dict[str, Any],
        pagination: Dict[str, int]
    ) -> Tuple[List[ResearchPaper], int]:
        """Optimized research paper search with filters"""
        
        # Start with base query
        query = db.query(ResearchPaper).distinct()
        
        # Apply filters efficiently
        if filters.get('paper_types'):
            query = query.filter(ResearchPaper.paper_type.in_(filters['paper_types']))
        
        if filters.get('start_date'):
            query = query.filter(ResearchPaper.created_at >= filters['start_date'])
        
        if filters.get('end_date'):
            query = query.filter(ResearchPaper.created_at <= filters['end_date'])
        
        if filters.get('file_name'):
            query = query.filter(
                ResearchPaper.file_name.ilike(f"%{filters['file_name']}%")
            )
        
        # Score range filters
        if filters.get('min_score'):
            query = query.filter(ResearchPaper.total_score >= filters['min_score'])
        
        if filters.get('max_score'):
            query = query.filter(ResearchPaper.total_score <= filters['max_score'])
        
        # Confidence filter
        if filters.get('min_confidence'):
            query = query.filter(ResearchPaper.confidence >= filters['min_confidence'])
        
        # Keyword search optimization
        if filters.get('keywords'):
            keyword_filter = db.query(ResearchPaperKeyword.research_paper_id).filter(
                ResearchPaperKeyword.keyword.in_(filters['keywords'])
            ).subquery()
            query = query.filter(ResearchPaper.id.in_(keyword_filter))
        
        # Category score filters (complex optimization)
        if filters.get('category_scores'):
            for category, score_range in filters['category_scores'].items():
                score_subquery = db.query(ResearchPaperScore.research_paper_id).filter(
                    ResearchPaperScore.category == category,
                    ResearchPaperScore.score >= score_range.get('min', 0),
                    ResearchPaperScore.score <= score_range.get('max', 100)
                ).subquery()
                query = query.filter(ResearchPaper.id.in_(score_subquery))
        
        # Get total count before pagination
        total_count = query.count()
        
        # Apply ordering and pagination
        order_by = filters.get('order_by', 'created_at')
        order_dir = desc if filters.get('order_dir') == 'desc' else asc
        
        if hasattr(ResearchPaper, order_by):
            query = query.order_by(order_dir(getattr(ResearchPaper, order_by)))
        
        # Apply pagination
        page = pagination.get('page', 1)
        page_size = pagination.get('page_size', 10)
        offset = (page - 1) * page_size
        
        papers = query.offset(offset).limit(page_size).all()
        
        return papers, total_count
    
    @staticmethod
    def get_paper_with_relations_optimized(
        db: Session,
        paper_id: int
    ) -> Optional[ResearchPaper]:
        """Get research paper with all relations in optimized single query"""
        
        return db.query(ResearchPaper).options(
            joinedload(ResearchPaper.scores),
            joinedload(ResearchPaper.keywords),
            joinedload(ResearchPaper.comments)
        ).filter(ResearchPaper.id == paper_id).first()
    
    @staticmethod
    def get_user_statistics_optimized(db: Session, user_id: int) -> Dict[str, Any]:
        """Get user statistics with optimized aggregation queries"""
        
        # Session statistics
        session_stats = db.query(
            func.count(ChatSession.id).label('total_sessions'),
            func.sum(ChatSession.message_count).label('total_messages'),
            func.max(ChatSession.last_message_at).label('last_activity')
        ).filter(ChatSession.user_id == user_id).first()
        
        # Messages by type
        message_stats = db.query(
            ChatMessage.message_type,
            func.count(ChatMessage.id).label('count')
        ).join(ChatSession).filter(
            ChatSession.user_id == user_id
        ).group_by(ChatMessage.message_type).all()
        
        # Recent activity (last 30 days)
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        recent_activity = db.query(ChatSession).filter(
            ChatSession.user_id == user_id,
            ChatSession.last_message_at >= thirty_days_ago
        ).count()
        
        return {
            'total_sessions': session_stats.total_sessions or 0,
            'total_messages': session_stats.total_messages or 0,
            'last_activity': session_stats.last_activity,
            'messages_by_type': {msg.message_type: msg.count for msg in message_stats},
            'recent_activity_30_days': recent_activity
        }

class BulkOperations:
    """Optimized bulk database operations"""
    
    @staticmethod
    def bulk_create_chat_messages(
        db: Session,
        messages: List[Dict[str, Any]]
    ) -> List[ChatMessage]:
        """Bulk create chat messages for better performance"""
        
        try:
            # Use bulk_insert_mappings for efficiency
            db.bulk_insert_mappings(ChatMessage, messages)
            db.commit()
            
            # Return the created messages (simplified version)
            return [ChatMessage(**msg) for msg in messages]
            
        except Exception as e:
            db.rollback()
            logger.error(f"Bulk message creation failed: {e}")
            raise
    
    @staticmethod
    def bulk_update_session_message_counts(
        db: Session,
        session_updates: List[Dict[str, Any]]
    ):
        """Bulk update session message counts"""
        
        try:
            db.bulk_update_mappings(ChatSession, session_updates)
            db.commit()
            
        except Exception as e:
            db.rollback()
            logger.error(f"Bulk session update failed: {e}")
            raise

class CacheManager:
    """Query result caching for frequently accessed data"""
    
    def __init__(self, redis_client=None):
        self.redis_client = redis_client
        self.cache_ttl = 300  # 5 minutes
    
    def get_cached_user_sessions(self, user_id: int) -> Optional[List[Dict]]:
        """Get cached user sessions"""
        if not self.redis_client:
            return None
        
        cache_key = f"user_sessions:{user_id}"
        try:
            cached_data = self.redis_client.get(cache_key)
            if cached_data:
                return eval(cached_data)  # Note: Use json in production
        except Exception as e:
            logger.error(f"Cache retrieval error: {e}")
        
        return None
    
    def cache_user_sessions(self, user_id: int, sessions: List[Dict]):
        """Cache user sessions"""
        if not self.redis_client:
            return
        
        cache_key = f"user_sessions:{user_id}"
        try:
            self.redis_client.setex(
                cache_key, 
                self.cache_ttl, 
                str(sessions)  # Note: Use json in production
            )
        except Exception as e:
            logger.error(f"Cache setting error: {e}")
    
    def invalidate_user_cache(self, user_id: int):
        """Invalidate user-specific cache"""
        if not self.redis_client:
            return
        
        cache_key = f"user_sessions:{user_id}"
        try:
            self.redis_client.delete(cache_key)
        except Exception as e:
            logger.error(f"Cache invalidation error: {e}")

class QueryPerformanceMonitor:
    """Monitor and log query performance"""
    
    @staticmethod
    def log_slow_query(query: str, execution_time: float, threshold: float = 1.0):
        """Log slow queries for optimization"""
        if execution_time > threshold:
            logger.warning(
                f"Slow query detected: {execution_time:.2f}s",
                extra={
                    "query": query[:200],  # Truncate long queries
                    "execution_time": execution_time,
                    "threshold": threshold
                }
            )
    
    @staticmethod
    def analyze_query_plan(db: Session, query: str) -> Dict[str, Any]:
        """Analyze query execution plan (PostgreSQL specific)"""
        try:
            result = db.execute(text(f"EXPLAIN ANALYZE {query}"))
            plan_data = result.fetchall()
            
            return {
                "plan": [row[0] for row in plan_data],
                "analyzed_at": datetime.utcnow()
            }
        except Exception as e:
            logger.error(f"Query plan analysis failed: {e}")
            return {"error": str(e)}
