import logging
import time
from typing import Optional, Tuple
from pinecone import Pinecone, ServerlessSpec, PineconeException
from dotenv import load_dotenv
import os

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Initialize Pinecone client with retry mechanism
def init_pinecone() -> Tuple[bool, Optional[Pinecone]]:
    """
    Initialize Pinecone client with retry mechanism.
    
    Returns:
        Tuple[bool, Optional[Pinecone]]: (success, pc) where success is a boolean
        indicating if initialization was successful, and pc is the Pinecone client instance.
    """
    pinecone_api_key = os.getenv("PINECONE_API_KEY")
    
    if not pinecone_api_key:
        logger.error("PINECONE_API_KEY not found in environment variables")
        return False, None
    
    max_retries = 3
    retry_delay = 2  # seconds
    
    for attempt in range(max_retries):
        try:
            pc = Pinecone(api_key=pinecone_api_key)
            # Test the connection
            pc.list_indexes()
            logger.info("Successfully connected to Pinecone")
            return True, pc
        except Exception as e:
            if attempt < max_retries - 1:
                logger.warning(
                    f"Attempt {attempt + 1} failed to connect to Pinecone. "
                    f"Retrying in {retry_delay} seconds... Error: {str(e)}"
                )
                time.sleep(retry_delay)
                retry_delay *= 2  # Exponential backoff
            else:
                logger.error(
                    f"Failed to connect to Pinecone after {max_retries} attempts. "
                    f"Last error: {str(e)}"
                )
                return False, None
    
    return False, None

# Initialize Pinecone
pinecone_initialized, pc = init_pinecone()
if not pinecone_initialized:
    logger.warning("Pinecone initialization failed. Vector search functionality will be disabled.")

# Index names
DOCTOR_INDEX = "doctorfinalindex"
PATIENT_INDEX = "patientindex"
EXPERTOPINION_INDEX = "expertopinionindex"
PATIENTOPINION_INDEX = "patientopinionindex"
EMBEDDING_DIMENSION = 1536  # Default dimension for OpenAI embeddings

def init_doctor_db() -> None:
    """
    Initialize the doctor vector database index if it doesn't exist.
    """
    if DOCTOR_INDEX not in pc.list_indexes().names():
        pc.create_index(
            name=DOCTOR_INDEX,
            dimension=EMBEDDING_DIMENSION,
            metric="cosine",
            spec=ServerlessSpec(
                cloud='aws',
                region='us-east-1'
            )
        )
    return pc.Index(DOCTOR_INDEX)

def init_patient_db() -> None:
    """
    Initialize the patient vector database index if it doesn't exist.
    """
    if PATIENT_INDEX not in pc.list_indexes().names():
        pc.create_index(
            name=PATIENT_INDEX,
            dimension=EMBEDDING_DIMENSION,
            metric="cosine",
            spec=ServerlessSpec(
                cloud='aws',
                region='us-west-2'
            )
        )
    return pc.Index(PATIENT_INDEX)

def init_expertopinion_db() -> None:
    """
    Initialize the expert opinion vector database index if it doesn't exist.
    """
    if EXPERTOPINION_INDEX not in pc.list_indexes().names():
        pc.create_index(
            name=EXPERTOPINION_INDEX,
            dimension=EMBEDDING_DIMENSION,
            metric="cosine",
            spec=ServerlessSpec(
                cloud='aws',
                region='us-east-1'
            )
        )
    return pc.Index(EXPERTOPINION_INDEX)

def init_patientopinion_db() -> None:
    """
    Initialize the patient opinion vector database index if it doesn't exist.
    """
    if PATIENTOPINION_INDEX not in pc.list_indexes().names():
        pc.create_index(
            name=PATIENTOPINION_INDEX,
            dimension=EMBEDDING_DIMENSION,
            metric="cosine",
            spec=ServerlessSpec(
                cloud='aws',
                region='us-east-1'
            )
        )
    return pc.Index(PATIENTOPINION_INDEX)

