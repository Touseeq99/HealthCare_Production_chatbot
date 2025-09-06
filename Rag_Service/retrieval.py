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
    # Get similar documents
    docs = vector_doc_db.similarity_search(query, k=6)
    
    reranker = PineconeRerank()
    
    reranked_docs = reranker.rerank(
        query=query,
        documents=[doc.page_content for doc in docs]
    )
    return reranked_docs

