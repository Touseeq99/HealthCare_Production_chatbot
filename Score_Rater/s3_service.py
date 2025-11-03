import os
import boto3
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError, BotoCoreError
import hashlib

from .config import config

# Configure logging
logging.basicConfig(
    level=getattr(logging, os.getenv('LOG_LEVEL', 'INFO')),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class S3Service:
    def __init__(self):
        """Initialize with secure defaults."""
        s3_config = config.s3_config
        self.bucket_name = s3_config['bucket_name']
        self.download_dir = s3_config['download_dir']
        self.prefix = s3_config['prefix']
        self.max_daily_downloads = config.processing_config['max_daily_downloads']
        self.supported_file_types = set(config.processing_config['supported_file_types'])
        self.chunk_size = config.processing_config['chunk_size']
        
        # Initialize S3 client with secure configuration
        self.s3_client = self._create_s3_client()
        
        # Track downloads
        self._reset_daily_counter()
    
    def _create_s3_client(self):
        """Create a secure S3 client with appropriate configuration."""
        s3_config = config.s3_config
        boto_config = BotoConfig(
            region_name=s3_config['region_name'],
            signature_version='s3v4',
            retries={
                'max_attempts': 3,
                'mode': 'standard'
            },
            s3={
                'use_accelerate_endpoint': False,
                'addressing_style': 'virtual'
            }
        )
        
        return boto3.client(
            's3',
            aws_access_key_id=s3_config['aws_access_key_id'],
            aws_secret_access_key=s3_config['aws_secret_access_key'],
            config=boto_config
        )
    
    def _reset_daily_counter(self):
        """Reset the daily download counter."""
        self.daily_downloads = 0
        self.last_reset_date = datetime.utcnow().date()
        logger.info("Daily download counter reset")
    
    def _can_download(self) -> bool:
        """Check if we can proceed with downloads."""
        if datetime.utcnow().date() > self.last_reset_date:
            self._reset_daily_counter()
        return self.daily_downloads < self.max_daily_downloads
    
    def list_files(self) -> List[Dict[str, Any]]:
        """List files in S3 bucket with basic validation."""
        try:
            response = self.s3_client.list_objects_v2(
                Bucket=self.bucket_name,
                Prefix=self.prefix,
                MaxKeys=1000  # Limit number of objects returned
            )
            return [
                {
                    'key': obj['Key'],
                    'size': obj['Size'],
                    'last_modified': obj['LastModified']
                }
                for obj in response.get('Contents', [])
                if self._is_valid_file(obj)
            ]
        except (ClientError, BotoCoreError) as e:
            logger.error(f"Error listing S3 files: {e}")
            return []
    
    def _is_valid_file(self, obj: Dict[str, Any]) -> bool:
        """Validate if the S3 object is a supported file."""
        if obj['Key'].endswith('/'):
            return False
        return any(obj['Key'].lower().endswith(ext) for ext in self.supported_file_types)
    
    @staticmethod
    def _sanitize_filename(s3_key: str) -> str:
        """Sanitize and extract filename from S3 key."""
        if not s3_key or '..' in s3_key or '//' in s3_key:
            return ""
        return os.path.basename(s3_key)
    
    def download_file(self, s3_key: str) -> Optional[Path]:
        """
        Securely download a file from S3.
        
        Args:
            s3_key: The S3 object key to download
            
        Returns:
            Path to the downloaded file if successful, None otherwise
        """
        if not self._can_download():
            logger.warning(f"Daily download limit of {self.max_daily_downloads} reached")
            return None
        
        file_name = self._sanitize_filename(s3_key)
        if not file_name:
            logger.warning(f"Invalid S3 key: {s3_key}")
            return None
            
        file_ext = os.path.splitext(file_name)[1].lower()
        if not file_ext or file_ext not in self.supported_file_types:
            logger.warning(f"Skipping unsupported file type: {file_name}")
            return None
            
        local_path = self.download_dir / file_name
        temp_path = local_path.with_suffix(f'.{self._generate_temp_suffix()}')
        
        try:
            # Download to temp file first
            self._download_to_temp(s3_key, temp_path)
            
            # Verify download
            if not self._verify_download(temp_path):
                raise Exception("Download verification failed")
                
            # Rename temp to final filename
            temp_path.rename(local_path)
            self.daily_downloads += 1
            
            logger.info(f"Downloaded {s3_key} to {local_path}")
            return local_path
            
        except Exception as e:
            logger.error(f"Failed to download {s3_key}: {e}")
            self._cleanup_failed_download(temp_path)
            return None
    
    def _download_to_temp(self, s3_key: str, temp_path: Path):
        """Download file to temporary location."""
        with open(temp_path, 'wb') as f:
            self.s3_client.download_fileobj(
                Bucket=self.bucket_name,
                Key=s3_key,
                Fileobj=f,
                Config=boto3.s3.transfer.TransferConfig(
                    multipart_chunksize=self.chunk_size,
                    max_concurrency=10,
                    use_threads=True
                )
            )
    
    @staticmethod
    def _verify_download(file_path: Path, min_size: int = 100) -> bool:
        """Verify the downloaded file meets minimum requirements."""
        try:
            return file_path.exists() and file_path.stat().st_size >= min_size
        except OSError:
            return False
    
    @staticmethod
    def _cleanup_failed_download(file_path: Path):
        """Clean up failed downloads."""
        try:
            if file_path.exists():
                file_path.unlink()
        except OSError as e:
            logger.warning(f"Failed to clean up {file_path}: {e}")
    
    @staticmethod
    def _generate_temp_suffix() -> str:
        """Generate a random suffix for temp files."""
        return hashlib.md5(str(datetime.utcnow().timestamp()).encode()).hexdigest()[:8]
    
    def process_new_files(self) -> List[Path]:
        """
        Process new files from S3 bucket up to the daily limit.
        
        Returns:
            List of paths to successfully downloaded files
        """
        downloaded_files = []
        
        try:
            # Get list of files from S3
            s3_files = self.list_files()
            logger.info(f"Found {len(s3_files)} files in S3 bucket")
            
            # Process files until we reach the daily limit
            for file_info in s3_files:
                if not self._can_download():
                    logger.info("Daily download limit reached")
                    break
                    
                local_path = self.download_file(file_info['key'])
                if local_path:
                    downloaded_files.append(local_path)
                    
        except Exception as e:
            logger.error(f"Error processing files: {e}")
        
        logger.info(f"Successfully downloaded {len(downloaded_files)} files")
        return downloaded_files
    
    def get_remaining_daily_downloads(self) -> int:
        """Get the number of remaining downloads for the current day."""
        self._can_download()  # This will reset counter if needed
        return max(0, self.max_daily_downloads - self.daily_downloads)


def main():
    """Example usage of the S3Service."""
    s3_service = S3Service()
    print(f"Remaining daily downloads: {s3_service.get_remaining_daily_downloads()}")
    
    # Process new files
    downloaded_files = s3_service.process_new_files()
    print(f"Downloaded {len(downloaded_files)} files:")
    for file_path in downloaded_files:
        print(f"- {file_path}")


if __name__ == "__main__":
    main()
