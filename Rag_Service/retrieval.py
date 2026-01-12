import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langchain_pinecone import PineconeRerank
from langchain_openai import OpenAIEmbeddings
from langchain_core.documents import Document
from dotenv import load_dotenv
import pinecone
from langchain_pinecone import PineconeVectorStore 
from data_utils.vector_db import init_doctor_db, init_patient_db, DOCTOR_INDEX
import os
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()


# Initialize the doctor index
init_doctor_db()

# Create PineconeVectorStore instance
embeddings = OpenAIEmbeddings(api_key=os.getenv("OPENAI_API_KEY"))
vector_doc_db = PineconeVectorStore.from_existing_index(
    index_name=DOCTOR_INDEX,
    embedding=embeddings
)

def query_doc(query: str):
    logger.info(f"Starting query_doc with query: {query[:100]}...")
    
    try:
        # Get similar documents
        logger.info("Attempting similarity search...")
        docs = vector_doc_db.similarity_search(query, k=8)
        logger.info(f"Retrieved {len(docs)} documents from vector DB")
        
        # Create mapping of document content to metadata (including file names)
        content_to_metadata = {}
        for i, doc in enumerate(docs):
            logger.debug(f"Document {i}: page_content length={len(doc.page_content)}, metadata keys={list(doc.metadata.keys())}")
            content_to_metadata[doc.page_content] = doc.metadata
        
        logger.info("Starting reranking...")
        reranker = PineconeRerank(top_n=5)
        
        reranked_docs = reranker.rerank(
            query=query,
            documents=[doc.page_content for doc in docs]
        )
        logger.info(f"Reranking completed, got {len(reranked_docs)} reranked docs")
        
        # Extract file names for reranked documents
        reranked_file_names = []
        for i, reranked_doc in enumerate(reranked_docs):
            # Handle PineconeRerank nested structure
            if isinstance(reranked_doc, dict):
                # Extract text from nested structure: {'document': {'text': '...'}}
                if 'document' in reranked_doc and isinstance(reranked_doc['document'], dict):
                    doc_content = reranked_doc['document'].get('text', '') or str(reranked_doc['document'])
                    logger.debug(f"Reranked doc {i}: nested dict format, extracted content length={len(doc_content)}")
                else:
                    # Fallback for other dict formats
                    doc_content = reranked_doc.get('text', '') or reranked_doc.get('content', '') or str(reranked_doc)
                    logger.debug(f"Reranked doc {i}: flat dict format, extracted content length={len(doc_content)}")
            else:
                # If reranked_doc is a string, use it directly
                doc_content = str(reranked_doc)
                logger.debug(f"Reranked doc {i}: string format, length={len(doc_content)}")
            
            # Find the original document metadata for this content
            original_metadata = content_to_metadata.get(doc_content, {})
            file_name = original_metadata.get('file_name', 'Unknown')
            logger.debug(f"Reranked doc {i}: file_name={file_name}")
            reranked_file_names.append(file_name)
        
        result = {
            'reranked_docs': reranked_docs,
            'file_names': reranked_file_names
        }
        logger.info("query_doc completed successfully")
        return result
        
    except Exception as e:
        logger.error(f"Error in query_doc: {str(e)}", exc_info=True)
        raise

