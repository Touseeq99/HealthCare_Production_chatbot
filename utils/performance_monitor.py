"""
Performance monitoring utilities for evidence engine
"""

import time
import logging
from functools import wraps
from typing import Any, Callable

logger = logging.getLogger(__name__)

def monitor_performance(func: Callable) -> Callable:
    """
    Decorator to monitor function performance
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()
        
        try:
            result = func(*args, **kwargs)
            execution_time = time.time() - start_time
            
            # Log performance metrics
            logger.info(
                f"Performance: {func.__name__} executed in {execution_time:.3f}s",
                extra={
                    "function": func.__name__,
                    "execution_time": execution_time,
                    "args_count": len(args),
                    "kwargs_count": len(kwargs)
                }
            )
            
            # Alert on slow queries
            if execution_time > 1.0:  # More than 1 second
                logger.warning(
                    f"Slow query detected: {func.__name__} took {execution_time:.3f}s",
                    extra={
                        "function": func.__name__,
                        "execution_time": execution_time,
                        "performance_issue": True
                    }
                )
            
            return result
            
        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(
                f"Performance: {func.__name__} failed after {execution_time:.3f}s - {str(e)}",
                extra={
                    "function": func.__name__,
                    "execution_time": execution_time,
                    "error": str(e)
                },
                exc_info=True
            )
            raise
    
    return wrapper

def log_database_query(query: str, execution_time: float, result_count: int = None):
    """
    Log database query performance
    """
    logger.info(
        f"DB Query: {query[:100]}... executed in {execution_time:.3f}s",
        extra={
            "query_type": "database",
            "execution_time": execution_time,
            "result_count": result_count,
            "query_preview": query[:100] if query else None
        }
    )
    
    if execution_time > 0.5:  # More than 500ms
        logger.warning(
            f"Slow DB query detected: {execution_time:.3f}s",
            extra={
                "query_type": "database",
                "execution_time": execution_time,
                "performance_issue": True
            }
        )
