"""
Cache invalidation triggers for evidence engine
Automatically invalidates cache when data changes
"""

import logging
from typing import Optional
from sqlalchemy.orm import Session
from database.models import ResearchPaper, ResearchPaperScore, ResearchPaperKeyword, ResearchPaperComment
from utils.evidence_cache import evidence_cache

logger = logging.getLogger(__name__)

class EvidenceCacheInvalidator:
    """Handles automatic cache invalidation when data changes"""
    
    @staticmethod
    def invalidate_on_paper_change(db: Session, paper_id: Optional[int] = None):
        """Invalidate cache when research papers are modified"""
        try:
            # Invalidate general search and file caches
            evidence_cache.invalidate('search')
            evidence_cache.invalidate('files')
            evidence_cache.invalidate('count')
            
            # Invalidate specific paper cache if ID provided
            if paper_id:
                evidence_cache.invalidate('paper', paper_id)
            
            # Invalidate categories and paper types if they might have changed
            evidence_cache.invalidate('categories')
            evidence_cache.invalidate('paper_types')
            
            logger.info(f"Cache invalidated due to paper change (paper_id: {paper_id})")
            
        except Exception as e:
            logger.error(f"Error invalidating cache on paper change: {e}")
    
    @staticmethod
    def invalidate_on_score_change(db: Session, paper_id: Optional[int] = None):
        """Invalidate cache when research paper scores are modified"""
        try:
            # Invalidate search results that depend on scores
            evidence_cache.invalidate('search')
            evidence_cache.invalidate('files')
            evidence_cache.invalidate('count')
            
            # Invalidate specific paper cache if ID provided
            if paper_id:
                evidence_cache.invalidate('paper', paper_id)
            
            # Invalidate categories as they might be affected
            evidence_cache.invalidate('categories')
            
            logger.info(f"Cache invalidated due to score change (paper_id: {paper_id})")
            
        except Exception as e:
            logger.error(f"Error invalidating cache on score change: {e}")
    
    @staticmethod
    def invalidate_on_keyword_change(db: Session, paper_id: Optional[int] = None):
        """Invalidate cache when keywords are modified"""
        try:
            # Invalidate search results that depend on keywords
            evidence_cache.invalidate('search')
            evidence_cache.invalidate('files')
            evidence_cache.invalidate('count')
            
            # Invalidate specific paper cache if ID provided
            if paper_id:
                evidence_cache.invalidate('paper', paper_id)
            
            logger.info(f"Cache invalidated due to keyword change (paper_id: {paper_id})")
            
        except Exception as e:
            logger.error(f"Error invalidating cache on keyword change: {e}")
    
    @staticmethod
    def invalidate_on_comment_change(db: Session, paper_id: Optional[int] = None):
        """Invalidate cache when comments are modified"""
        try:
            # Invalidate search results that depend on comments
            evidence_cache.invalidate('search')
            evidence_cache.invalidate('files')
            evidence_cache.invalidate('count')
            
            # Invalidate specific paper cache if ID provided
            if paper_id:
                evidence_cache.invalidate('paper', paper_id)
            
            logger.info(f"Cache invalidated due to comment change (paper_id: {paper_id})")
            
        except Exception as e:
            logger.error(f"Error invalidating cache on comment change: {e}")

# Global invalidator instance
cache_invalidator = EvidenceCacheInvalidator()

# SQLAlchemy event listeners for automatic cache invalidation
def setup_cache_listeners():
    """Setup SQLAlchemy event listeners for automatic cache invalidation"""
    
    def after_paper_insert(mapper, connection, target):
        cache_invalidator.invalidate_on_paper_change(None, target.id)
    
    def after_paper_update(mapper, connection, target):
        cache_invalidator.invalidate_on_paper_change(None, target.id)
    
    def after_paper_delete(mapper, connection, target):
        cache_invalidator.invalidate_on_paper_change(None, target.id)
    
    def after_score_insert(mapper, connection, target):
        cache_invalidator.invalidate_on_score_change(None, target.research_paper_id)
    
    def after_score_update(mapper, connection, target):
        cache_invalidator.invalidate_on_score_change(None, target.research_paper_id)
    
    def after_score_delete(mapper, connection, target):
        cache_invalidator.invalidate_on_score_change(None, target.research_paper_id)
    
    def after_keyword_insert(mapper, connection, target):
        cache_invalidator.invalidate_on_keyword_change(None, target.research_paper_id)
    
    def after_keyword_update(mapper, connection, target):
        cache_invalidator.invalidate_on_keyword_change(None, target.research_paper_id)
    
    def after_keyword_delete(mapper, connection, target):
        cache_invalidator.invalidate_on_keyword_change(None, target.research_paper_id)
    
    def after_comment_insert(mapper, connection, target):
        cache_invalidator.invalidate_on_comment_change(None, target.research_paper_id)
    
    def after_comment_update(mapper, connection, target):
        cache_invalidator.invalidate_on_comment_change(None, target.research_paper_id)
    
    def after_comment_delete(mapper, connection, target):
        cache_invalidator.invalidate_on_comment_change(None, target.research_paper_id)
    
    # Register event listeners
    from sqlalchemy import event
    
    event.listen(ResearchPaper, 'after_insert', after_paper_insert)
    event.listen(ResearchPaper, 'after_update', after_paper_update)
    event.listen(ResearchPaper, 'after_delete', after_paper_delete)
    
    event.listen(ResearchPaperScore, 'after_insert', after_score_insert)
    event.listen(ResearchPaperScore, 'after_update', after_score_update)
    event.listen(ResearchPaperScore, 'after_delete', after_score_delete)
    
    event.listen(ResearchPaperKeyword, 'after_insert', after_keyword_insert)
    event.listen(ResearchPaperKeyword, 'after_update', after_keyword_update)
    event.listen(ResearchPaperKeyword, 'after_delete', after_keyword_delete)
    
    event.listen(ResearchPaperComment, 'after_insert', after_comment_insert)
    event.listen(ResearchPaperComment, 'after_update', after_comment_update)
    event.listen(ResearchPaperComment, 'after_delete', after_comment_delete)
    
    logger.info("Cache invalidation event listeners setup complete")
