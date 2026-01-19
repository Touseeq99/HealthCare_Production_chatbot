import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langchain_pinecone import PineconeRerank
from langchain_openai import OpenAIEmbeddings
from langchain_core.documents import Document
from dotenv import load_dotenv
import pinecone
from langchain_pinecone import PineconeVectorStore 
from data_utils.vector_db import (
    init_doctor_db, init_patient_db, init_expertopinion_db, init_patientopinion_db,
    DOCTOR_INDEX, EXPERTOPINION_INDEX, PATIENTOPINION_INDEX
)
import os
import logging
import asyncio

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()


# Initialize the indices
init_doctor_db()
init_expertopinion_db()
init_patientopinion_db()

# Create PineconeVectorStore instances
embeddings = OpenAIEmbeddings(api_key=os.getenv("OPENAI_API_KEY"))

vector_doc_db = PineconeVectorStore.from_existing_index(
    index_name=DOCTOR_INDEX,
    embedding=embeddings
)

vector_expert_db = PineconeVectorStore.from_existing_index(
    index_name=EXPERTOPINION_INDEX,
    embedding=embeddings
)

vector_patient_db = PineconeVectorStore.from_existing_index(
    index_name=PATIENTOPINION_INDEX,
    embedding=embeddings
)

# Map for easy access
vector_stores = {
    'research': vector_doc_db,
    'expert': vector_expert_db,
    'patient': vector_patient_db
}

def _process_docs(docs, query):
    """Helper to process and rerank documents"""
    logger.info(f"Retrieved {len(docs)} documents from vector DB")
    
    # Create mapping of document content to metadata (including file names)
    content_to_metadata = {}
    for doc in docs:
        content_to_metadata[doc.page_content] = doc.metadata
    
    logger.info("Starting reranking...")
    # Reduced top_n to 3 for speed
    reranker = PineconeRerank(top_n=3)
    
    reranked_docs = reranker.rerank(
        query=query,
        documents=[doc.page_content for doc in docs]
    )
    logger.info(f"Reranking completed, got {len(reranked_docs)} reranked docs")
    
    # Extract file names for reranked documents
    reranked_file_names = []
    for reranked_doc in reranked_docs:
        # Handle PineconeRerank nested structure
        if isinstance(reranked_doc, dict):
            # Extract text from nested structure: {'document': {'text': '...'}}
            if 'document' in reranked_doc and isinstance(reranked_doc['document'], dict):
                doc_content = reranked_doc['document'].get('text', '') or str(reranked_doc['document'])
            else:
                # Fallback for other dict formats
                doc_content = reranked_doc.get('text', '') or reranked_doc.get('content', '') or str(reranked_doc)
        else:
            # If reranked_doc is a string, use it directly
            doc_content = str(reranked_doc)
        
        # Find the original document metadata for this content
        original_metadata = content_to_metadata.get(doc_content, {})
        file_name = original_metadata.get('file_name', 'Unknown')
        reranked_file_names.append(file_name)
    
    result = {
        'reranked_docs': reranked_docs,
        'file_names': reranked_file_names
    }
    return result

def query_doc(query: str, index_type: str = 'research'):
    """
    Synchronous query function.
    index_type: 'research' (default), 'expert', or 'patient'
    """
    logger.info(f"Starting query_doc with query: {query[:100]}... on index: {index_type}")
    
    try:
        store = vector_stores.get(index_type)
        if not store:
            raise ValueError(f"Invalid index_type: {index_type}")

        # Get similar documents - Reduced k to 5 for speed
        logger.info("Attempting similarity search...")
        docs = store.similarity_search(query, k=5)
        
        result = _process_docs(docs, query)
        
        logger.info("query_doc completed successfully")
        return result
        
    except Exception as e:
        logger.error(f"Error in query_doc: {str(e)}", exc_info=True)
        raise

async def aquery_doc(query: str, index_type: str = 'research'):
    """
    Asynchronous query function.
    index_type: 'research' (default), 'expert', or 'patient'
    """
    logger.info(f"Starting async query_doc with query: {query[:100]}... on index: {index_type}")
    
    try:
        store = vector_stores.get(index_type)
        if not store:
            raise ValueError(f"Invalid index_type: {index_type}")

        # Get similar documents asynchronously - Reduced k to 5 for speed
        logger.info(f"Attempting async similarity search on {index_type}...")
        docs = await store.asimilarity_search(query, k=5)
        
        # Run processing/reranking in a thread pool
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, _process_docs, docs, query)
        
        logger.info(f"Async query_doc on {index_type} completed successfully")
        return result
        
    except Exception as e:
        logger.error(f"Error in async query_doc: {str(e)}", exc_info=True)
        raise

