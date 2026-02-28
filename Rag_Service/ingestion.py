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
    Ingest a document into the vector database with rating metadata AND document metadata.
    
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
        
        # Batch all documents for efficient Pinecone upsert
        all_docs = []
        for chunk in chunks:
            # Merge rating metadata with document metadata (file_name, page, source, etc.)
            chunk_metadata = rating_meta.copy()
            
            # Extract key fields from document parser metadata
            parser_meta = chunk.get('metadata', {})
            chunk_metadata.update({
                'file_name': parser_meta.get('file_name', os.path.basename(file)),
                'source': parser_meta.get('source', file),
                'page_number': parser_meta.get('page_number', 0),
                'chunk_id': parser_meta.get('chunk_id', 0),
                'total_chunks': parser_meta.get('total_chunks', 0),
                'word_count': parser_meta.get('word_count', 0),
            })
            
            doc = Document(
                page_content=chunk['text'],
                metadata=chunk_metadata
            )
            all_docs.append(doc)
        
        # Batch insert (much faster than one-at-a-time)
        if all_docs:
            BATCH_SIZE = 50
            for i in range(0, len(all_docs), BATCH_SIZE):
                batch = all_docs[i:i + BATCH_SIZE]
                vector_Db_doc.add_documents(batch)
                logger.info(f"Ingested batch {i // BATCH_SIZE + 1} ({len(batch)} docs)")
            
            logger.info(f"Successfully ingested {len(all_docs)} chunks from {os.path.basename(file)}")
    except Exception as e:
        logger.error(f"Error ingesting {file}: {str(e)}")
        import traceback
        traceback.print_exc()
 





        
        
    