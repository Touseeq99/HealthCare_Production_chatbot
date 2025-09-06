from pinecone import Pinecone, ServerlessSpec
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()
pinecone_api_key = os.getenv("PINECONE_API_KEY")
pc = Pinecone(api_key=pinecone_api_key)

# Index names
DOCTOR_INDEX = "doctorindex"
PATIENT_INDEX = "patientindex"
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

