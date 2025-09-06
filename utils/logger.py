import logging
import sys
import os
import logging.handlers
from pythonjsonlogger import jsonlogger
from datetime import datetime
from typing import Dict, Any, Optional

from config import settings

def setup_logging() -> logging.Logger:
    """
    Configure JSON logging for the application.
    
    Returns:
        logging.Logger: Configured logger instance
    """
    # Get root logger
    logger = logging.getLogger()
    
    # Clear any existing handlers
    logger.handlers.clear()
    
    # Set log level from settings
    log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    logger.setLevel(log_level)
    
    # Create logs directory if it doesn't exist
    log_dir = 'logs'
    if not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True)
    
    # Create formatter
    formatter = jsonlogger.JsonFormatter(
        '%(asctime)s %(levelname)s %(name)s %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        json_ensure_ascii=False,
        json_indent=2 if settings.LOG_LEVEL.upper() == 'DEBUG' else None,
        timestamp=True
    )
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(log_level)
    
    # File handler - rotates daily
    file_handler = logging.handlers.TimedRotatingFileHandler(
        filename=os.path.join(log_dir, 'application.log'),
        when='midnight',
        backupCount=30,  # Keep logs for 30 days
        encoding='utf-8'
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(log_level)
    
    # Add handlers to the logger
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    
    # Configure uvicorn logging
    for log_name in ["uvicorn", "uvicorn.error", "uvicorn.access"]:
        uvicorn_logger = logging.getLogger(log_name)
        uvicorn_logger.handlers = []
        uvicorn_logger.propagate = True
    
    # Set log level for specific loggers
    logging.getLogger("uvicorn").setLevel(log_level)
    logging.getLogger("uvicorn.access").handlers = []
    logging.getLogger("uvicorn.error").handlers = []
    
    # Disable noisy loggers
    logging.getLogger("uvicorn.error").propagate = False
    
    return logger

# Create a logger instance
logger = setup_logging()

def get_logger(name: str) -> logging.Logger:
    """
    Get a logger with the specified name.
    
    Args:
        name: Name of the logger
        
    Returns:
        Configured logger instance
    """
    return logging.getLogger(name)
