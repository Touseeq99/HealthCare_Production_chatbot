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
import logging
import asyncio
from typing import List, Optional

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Initialize the indices (Done once on startup)
try:
    init_doctor_db()
    init_expertopinion_db()
    init_patientopinion_db()
except Exception as e:
    logger.error(f"Failed to initialize Pinecone indices: {e}")

# Global instances for reuse
embeddings = OpenAIEmbeddings(api_key=os.getenv("OPENAI_API_KEY"))

# Global Reranker - pay initialization price once
# Increased top_n from 3 to 5 for better recall on multi-faceted medical queries
try:
    reranker = PineconeRerank(top_n=5)
except Exception as e:
    logger.error(f"Failed to initialize Reranker: {e}")
    reranker = None

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


async def embed_query(query: str) -> List[float]:
    """
    Compute query embedding ONCE, to be reused across all 3 index searches.
    Eliminates 2 redundant OpenAI embedding API calls per question.
    """
    loop = asyncio.get_running_loop()
    embedding = await loop.run_in_executor(None, embeddings.embed_query, query)
    return embedding


def _process_docs(docs, query):
    """Helper to process and rerank documents. 
    Uses index-based mapping instead of broken content matching for file names."""
    if not docs:
        logger.info("No documents retrieved from vector DB.")
        return {'reranked_docs': [], 'file_names': []}

    logger.info(f"Retrieved {len(docs)} documents from vector DB")
    
    # Store original docs list for index-based lookup
    original_docs = docs
    doc_contents = [doc.page_content for doc in docs]
    
    # If reranker failed to init, return raw docs (fallback)
    if not reranker:
        logger.warning("Reranker not available, returning raw documents")
        return {
            'reranked_docs': [doc.page_content for doc in docs[:5]],
            'file_names': [doc.metadata.get('file_name', 'Unknown') for doc in docs[:5]]
        }

    logger.info("Starting reranking...")
    reranked_docs = reranker.rerank(
        query=query,
        documents=doc_contents
    )
    logger.info(f"Reranking completed, got {len(reranked_docs)} reranked docs")
    
    # Extract file names using index-based mapping (fixes the broken content matching)
    reranked_file_names = []
    reranked_contents = []
    
    for reranked_doc in reranked_docs:
        file_name = 'Unknown'
        doc_content = ''
        
        if isinstance(reranked_doc, dict):
            # Try to get index from reranker response for reliable mapping
            idx = reranked_doc.get('index')
            if idx is not None and 0 <= idx < len(original_docs):
                file_name = original_docs[idx].metadata.get('file_name', 'Unknown')
            
            # Extract text content
            if 'document' in reranked_doc and isinstance(reranked_doc['document'], dict):
                doc_content = reranked_doc['document'].get('text', '') or str(reranked_doc['document'])
            else:
                doc_content = reranked_doc.get('text', '') or reranked_doc.get('content', '') or str(reranked_doc)
            
            # Fallback: if index wasn't available, try content matching
            if file_name == 'Unknown' and doc_content:
                for orig_doc in original_docs:
                    if orig_doc.page_content == doc_content or doc_content in orig_doc.page_content:
                        file_name = orig_doc.metadata.get('file_name', 'Unknown')
                        break
        else:
            doc_content = str(reranked_doc)
        
        reranked_file_names.append(file_name)
        reranked_contents.append(doc_content)
    
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

        logger.info(f"Attempting similarity search on {index_type} (k=10)...")
        docs = store.similarity_search(query, k=10)
        
        result = _process_docs(docs, query)
        
        logger.info(f"query_doc on {index_type} completed successfully")
        return result
        
    except Exception as e:
        logger.error(f"Error in query_doc: {str(e)}", exc_info=True)
        raise


async def aquery_doc(query: str, index_type: str = 'research'):
    """
    Asynchronous query function (computes embedding internally).
    index_type: 'research' (default), 'expert', or 'patient'
    """
    logger.info(f"Starting async query_doc with query: {query[:100]}... on index: {index_type}")
    
    try:
        store = vector_stores.get(index_type)
        if not store:
            raise ValueError(f"Invalid index_type: {index_type}")

        logger.info(f"Attempting async similarity search on {index_type} (k=10)...")
        docs = await store.asimilarity_search(query, k=10)
        
        # Run processing/reranking in a thread pool
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, _process_docs, docs, query)
        
        logger.info(f"Async query_doc on {index_type} completed successfully")
        return result
        
    except Exception as e:
        logger.error(f"Error in async query_doc: {str(e)}", exc_info=True)
        raise


async def aquery_doc_with_embedding(query: str, query_embedding: List[float], index_type: str = 'research'):
    """
    Asynchronous query function that accepts a PRE-COMPUTED embedding vector.
    This eliminates redundant OpenAI embedding API calls when querying multiple indices
    with the same query (3 calls → 1 call).
    
    Args:
        query: The query text (used for reranking, not embedding)
        query_embedding: Pre-computed embedding vector from embed_query()
        index_type: 'research' (default), 'expert', or 'patient'
    """
    logger.info(f"Starting async query with pre-computed embedding on index: {index_type}")
    
    try:
        store = vector_stores.get(index_type)
        if not store:
            raise ValueError(f"Invalid index_type: {index_type}")

        # Use pre-computed embedding — NO redundant OpenAI call
        logger.info(f"Attempting vector search on {index_type} (k=10) with pre-computed embedding...")
        docs = await store.asimilarity_search_by_vector(query_embedding, k=10)
        
        # Run processing/reranking in a thread pool
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, _process_docs, docs, query)
        
        logger.info(f"Async query with embedding on {index_type} completed successfully")
        return result
        
    except Exception as e:
        logger.error(f"Error in async query with embedding: {str(e)}", exc_info=True)
        raise
