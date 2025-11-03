import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# S3 Configuration
S3_CONFIG = {
    'aws_access_key_id': os.getenv('AWS_ACCESS_KEY_ID'),
    'aws_secret_access_key': os.getenv('AWS_SECRET_ACCESS_KEY'),
    'region_name': os.getenv('AWS_REGION', 'us-east-1'),
    'bucket_name': os.getenv('S3_BUCKET_NAME', 'your-bucket-name'),
    'download_dir': os.path.join(os.path.dirname(os.path.dirname(__file__)), 'downloaded_files'),
    'prefix': 'documents/'  # The folder prefix in S3 where files are stored
}

# Processing Configuration
PROCESSING_CONFIG = {
    'max_daily_downloads': 1000,  # Maximum files to process per day
    'supported_file_types': ['.pdf', '.docx', '.txt', '.md']  # Supported file types
}

# Database Configuration
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://user:password@localhost/score_rater')

# Create download directory if it doesn't exist
os.makedirs(S3_CONFIG['download_dir'], exist_ok=True)
