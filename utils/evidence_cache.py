"""
Evidence Engine Caching Service
Provides Redis-based caching for evidence queries with intelligent cache management
"""

import json
import hashlib
import logging
from typing import Any, Optional, List, Dict, Union
from datetime import datetime, timedelta
import redis
from functools import wraps

from config import settings
from utils.auth_security import REDIS_AVAILABLE, redis_client

logger = logging.getLogger(__name__)

class EvidenceCacheService:
    """Caching service for evidence engine queries"""
    
    # Cache TTL configurations (in seconds)
    CACHE_TTL = {
        'search_results': 1800,      # 30 minutes
        'categories': 3600,         # 1 hour
        'paper_types': 3600,         # 1 hour
        'file_list': 600,           # 10 minutes
        'paper_details': 1800,      # 30 minutes
        'count_queries': 300,        # 5 minutes
    }
    
    # Cache key prefixes
    KEY_PREFIXES = {
        'search': 'evidence:search:',
        'categories': 'evidence:categories:',
        'paper_types': 'evidence:paper_types:',
        'files': 'evidence:files:',
        'paper': 'evidence:paper:',
        'count': 'evidence:count:',
    }
    
    def __init__(self):
        self.redis_available = REDIS_AVAILABLE
        if self.redis_available:
            logger.info("Evidence cache service initialized with Redis")
        else:
            logger.warning("Evidence cache service initialized without Redis (caching disabled)")
    
    def _generate_cache_key(self, prefix: str, data: Union[Dict, str, int]) -> str:
        """Generate a consistent cache key from data"""
        if isinstance(data, dict):
            # Sort dict keys for consistent hashing
            sorted_data = json.dumps(data, sort_keys=True, default=str)
        else:
            sorted_data = str(data)
        
        # Create hash of the data
        hash_obj = hashlib.md5(sorted_data.encode())
        data_hash = hash_obj.hexdigest()
        
        return f"{prefix}{data_hash}"
    
    def _serialize_data(self, data: Any) -> str:
        """Serialize data for Redis storage"""
        try:
            return json.dumps(data, default=str)
        except (TypeError, ValueError) as e:
            logger.error(f"Failed to serialize cache data: {e}")
            return None
    
    def _deserialize_data(self, data: str) -> Any:
        """Deserialize data from Redis"""
        try:
            return json.loads(data)
        except (TypeError, ValueError) as e:
            logger.error(f"Failed to deserialize cache data: {e}")
            return None
    
    def get(self, cache_type: str, data: Union[Dict, str, int]) -> Optional[Any]:
        """Get cached data"""
        if not self.redis_available:
            return None
        
        try:
            cache_key = self._generate_cache_key(self.KEY_PREFIXES[cache_type], data)
            cached_data = redis_client.get(cache_key)
            
            if cached_data:
                logger.debug(f"Cache hit for key: {cache_key}")
                return self._deserialize_data(cached_data)
            else:
                logger.debug(f"Cache miss for key: {cache_key}")
                return None
                
        except Exception as e:
            logger.error(f"Error getting cache data: {e}")
            return None
    
    def set(self, cache_type: str, data: Union[Dict, str, int], value: Any, ttl: Optional[int] = None) -> bool:
        """Set cached data"""
        if not self.redis_available:
            return False
        
        try:
            cache_key = self._generate_cache_key(self.KEY_PREFIXES[cache_type], data)
            serialized_value = self._serialize_data(value)
            
            if serialized_value is None:
                return False
            
            # Use default TTL for cache type if not specified
            if ttl is None:
                ttl = self.CACHE_TTL.get(cache_type, 300)  # Default 5 minutes
            
            success = redis_client.setex(cache_key, ttl, serialized_value)
            
            if success:
                logger.debug(f"Cached data for key: {cache_key} (TTL: {ttl}s)")
            else:
                logger.warning(f"Failed to cache data for key: {cache_key}")
            
            return success
            
        except Exception as e:
            logger.error(f"Error setting cache data: {e}")
            return False
    
    def invalidate(self, cache_type: str, data: Union[Dict, str, int] = None) -> bool:
        """Invalidate cached data"""
        if not self.redis_available:
            return False
        
        try:
            if data is None:
                # Invalidate all keys of this type
                pattern = f"{self.KEY_PREFIXES[cache_type]}*"
                keys = redis_client.keys(pattern)
                if keys:
                    deleted = redis_client.delete(*keys)
                    logger.info(f"Invalidated {deleted} cache keys for type: {cache_type}")
                    return deleted > 0
            else:
                # Invalidate specific key
                cache_key = self._generate_cache_key(self.KEY_PREFIXES[cache_type], data)
                deleted = redis_client.delete(cache_key)
                logger.debug(f"Invalidated cache key: {cache_key}")
                return deleted > 0
                
        except Exception as e:
            logger.error(f"Error invalidating cache data: {e}")
            return False
    
    def invalidate_all(self) -> bool:
        """Invalidate all evidence cache"""
        if not self.redis_available:
            return False
        
        try:
            pattern = "evidence:*"
            keys = redis_client.keys(pattern)
            if keys:
                deleted = redis_client.delete(*keys)
                logger.info(f"Invalidated {deleted} evidence cache keys")
                return deleted > 0
            return True
            
        except Exception as e:
            logger.error(f"Error invalidating all cache data: {e}")
            return False
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        if not self.redis_available:
            return {"available": False}
        
        try:
            info = redis_client.info()
            evidence_keys = redis_client.keys("evidence:*")
            
            return {
                "available": True,
                "total_keys": len(evidence_keys),
                "memory_usage": info.get("used_memory_human", "N/A"),
                "connected_clients": info.get("connected_clients", 0),
                "cache_hit_rate": info.get("keyspace_hits", 0) / max(info.get("keyspace_hits", 0) + info.get("keyspace_misses", 1), 1)
            }
            
        except Exception as e:
            logger.error(f"Error getting cache stats: {e}")
            return {"available": True, "error": str(e)}

# Global cache service instance
evidence_cache = EvidenceCacheService()

def cached_evidence_query(cache_type: str, ttl: Optional[int] = None):
    """
    Decorator for caching evidence queries
    
    Args:
        cache_type: Type of cache (search, categories, paper_types, files, paper)
        ttl: Custom TTL in seconds
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Generate cache key from function arguments
            cache_data = {
                'args': args[1:],  # Skip 'db' parameter
                'kwargs': kwargs
            }
            
            # Try to get from cache
            cached_result = evidence_cache.get(cache_type, cache_data)
            if cached_result is not None:
                return cached_result
            
            # Execute function and cache result
            result = func(*args, **kwargs)
            
            # Cache the result
            evidence_cache.set(cache_type, cache_data, result, ttl)
            
            return result
        
        return wrapper
    return decorator

def cached_count_query(cache_type: str = 'count', ttl: int = 300):
    """
    Decorator specifically for count queries
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Generate cache key for count query
            cache_data = {
                'function': func.__name__,
                'args': args[1:],  # Skip 'db' parameter
                'kwargs': kwargs
            }
            
            # Try to get from cache
            cached_result = evidence_cache.get(cache_type, cache_data)
            if cached_result is not None:
                return cached_result
            
            # Execute function and cache result
            result = func(*args, **kwargs)
            
            # Cache the result
            evidence_cache.set(cache_type, cache_data, result, ttl)
            
            return result
        
        return wrapper
    return decorator
