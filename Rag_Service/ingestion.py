import sys
import os
import logging
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data_utils.document_parser import DocumentChunker
from langchain_openai import OpenAIEmbeddings
from langchain_pinecone.vectorstores import PineconeVectorStore
from data_utils.vector_db import init_doctor_db, init_patient_db
from langchain_core.documents import Document


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

chunker = DocumentChunker()
index = init_doctor_db()
embeddings = OpenAIEmbeddings()
vector_Db_doc=PineconeVectorStore(index , embeddings)



def flatten_metadata(metadata):
    """Flatten nested metadata dictionaries into top-level keys with dot notation."""
    flat_metadata = {}
    for key, value in metadata.items():
        if key == 'page_metadata' and isinstance(value, dict):
            # Flatten page_metadata with a prefix
            for subkey, subvalue in value.items():
                flat_key = f"page_{subkey}"
                flat_metadata[flat_key] = subvalue
        elif isinstance(value, (str, int, float, bool)) or value is None:
            flat_metadata[key] = value
        elif isinstance(value, list) and all(isinstance(x, str) for x in value):
            flat_metadata[key] = value
        elif isinstance(value, dict):
            # Recursively flatten nested dictionaries
            for subkey, subvalue in value.items():
                flat_metadata[f"{key}_{subkey}"] = subvalue
    return flat_metadata

def ingestion_docs_doctor(file: str, rating_metadata: dict = None):
    """
    Ingest a document into the vector database with only rating metadata.
    
    Args:
        file (str): Path to the document file
        rating_metadata (dict, optional): Rating metadata from the rater.
            Should contain 'scores' and 'metadata' keys.
    """
    try:
        logger.info(f"Processing file: {file}")
        chunks = chunker.chunk_pdf(file)
        
        # Prepare rating metadata if provided
        rating_meta = {}
        if rating_metadata:
            # Add overall metadata
            rating_meta.update({
                'total_score': rating_metadata.get('metadata', {}).get('total_score'),
                'confidence': rating_metadata.get('metadata', {}).get('confidence'),
                'rating_keywords': ', '.join(rating_metadata.get('metadata', {}).get('Keywords', [])),
                'rating_comments': ' | '.join(rating_metadata.get('metadata', {}).get('comments', [])),
                'rating_penalties': ' | '.join(rating_metadata.get('metadata', {}).get('penalties', [])),
                'is_rated': True,
                'rating_source': 'CLARA-2'
            })
            
            # Add individual scores
            for score in rating_metadata.get('scores', []):
                category = score.get('category', '').lower().replace(' ', '_')
                rating_meta.update({
                    f'score_{category}': score.get('score'),
                    f'rationale_{category}': score.get('rationale', '')[:500]  # Limit rationale length
                })
        else:
            rating_meta['is_rated'] = False
        
        for chunk in chunks:
            # Create document with only rating metadata
            doc = Document(
                page_content=chunk['text'],
                metadata=rating_meta.copy()  # Use a copy to avoid reference issues
            )
            logger.debug(f"Adding chunk to vector database with rating metadata: {rating_meta}")
            vector_Db_doc.add_documents([doc])
    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
 





        
        
    