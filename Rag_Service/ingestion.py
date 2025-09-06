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

def ingestion_docs_doctor(file: str):
    try:
        logger.info(f"Processing file: {file}")
        chunks = chunker.chunk_pdf(file)
        for chunk in chunks:
            flat_metadata = flatten_metadata(chunk['metadata'])
            doc = Document(
                page_content=chunk['text'],
                metadata=flat_metadata
            )
            logger.info(f"Adding chunk to vector database: {flat_metadata}")
            vector_Db_doc.add_documents([doc])
    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()





if __name__ == "__main__":
    ingestion_docs_doctor("C:\\Users\\user\\Desktop\\metamed_backend\\AHAACC2023Guidelines.pdf")


        
        
    