from typing import List, Dict, Any, Optional, Tuple
from langchain.text_splitter import RecursiveCharacterTextSplitter, MarkdownHeaderTextSplitter
from langchain.docstore.document import Document as LangchainDocument
from PyPDF2 import PdfReader
import re
import logging
import os
from datetime import datetime, timezone
from dataclasses import dataclass, asdict

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class DocumentChunker:
    def __init__(
        self,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
        separators: Optional[List[str]] = None,
        keep_separator: bool = True,
        length_function=len,
    ):
        """
        Initialize the DocumentChunker with splitting configuration.
        
        Args:
            chunk_size: Maximum size of chunks to create
            chunk_overlap: Overlap between chunks to maintain context
            separators: List of separators to use for splitting
            keep_separator: Whether to keep the separators in the output
            length_function: Function to calculate length of text
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.separators = separators or ["\\n\\n", "\\n", " ", ""]
        self.keep_separator = keep_separator
        self.length_function = length_function
        
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=self.separators,
            keep_separator=self.keep_separator,
            length_function=self.length_function,
        )
        
        # Initialize metadata extraction patterns
        self.header_patterns = [
            (r'^(\d+\.\d+\.\d+\s+.+)$', 'section'),
            (r'^(\d+\.\d+\s+.+)$', 'subsection'),
            (r'^([A-Z][A-Z0-9a-z\s]+):$', 'field')
        ]

    def chunk_pdf(self, file_path: str) -> List[Dict[str, Any]]:
        """
        Extract text from a PDF and split it into meaningful chunks with metadata.
        
        Args:
            file_path: Path to the PDF file
            
        Returns:
            List of document chunks with rich metadata
        """
        try:
            # Extract document-level metadata
            doc_metadata = self._extract_metadata_from_pdf(file_path)
            
            # Extract text and page-level metadata
            text, page_metadata = self._extract_text_from_pdf(file_path)
            
            # Pre-process text
            text = self._preprocess_text(text)
            
            # Split into chunks
            documents = self.text_splitter.create_documents([text])
            
            # Add metadata to chunks
            chunks = []
            for i, doc in enumerate(documents):
                # Create chunk metadata
                chunk_meta = doc_metadata.copy()
                chunk_meta.update({
                    'chunk_id': i,
                    'chunk_size': len(doc.page_content),
                    'total_chunks': len(documents),
                    'chunk_start': text.find(doc.page_content),
                    'chunk_end': text.find(doc.page_content) + len(doc.page_content),
                    'content_type': 'text/plain',
                    'processing_timestamp': datetime.now(timezone.utc).isoformat(),
                })
                
                # Add content analysis
                content_analysis = self._analyze_content(doc.page_content)
                chunk_meta.update(content_analysis)
                
                # Determine which page this chunk belongs to
                current_position = chunk_meta['chunk_start']
                current_page = 1
                page_starts = [0]  # Page 1 starts at position 0
                
                # Find page boundaries in the text
                for page in page_metadata.get('pages', []):
                    if 'chunk_start' in page:
                        page_starts.append(page['chunk_start'])
                
                # Find the current page
                for j in range(1, len(page_starts)):
                    if current_position < page_starts[j]:
                        current_page = j
                        break
                
                chunk_meta['page_number'] = current_page
                
                # Add page-specific metadata if available
                if 'pages' in page_metadata and 0 <= current_page-1 < len(page_metadata['pages']):
                    chunk_meta.update({
                        'page_metadata': page_metadata['pages'][current_page-1]
                    })
                
                chunks.append({
                    'text': doc.page_content,
                    'metadata': chunk_meta
                })
            
            logger.info(f"Split PDF into {len(chunks)} chunks with rich metadata")
            return chunks
            
        except Exception as e:
            logger.error(f"Error processing PDF {file_path}: {str(e)}")
            logger.exception("Detailed error:")
            raise

    def _extract_metadata_from_pdf(self, file_path: str) -> Dict[str, Any]:
        """Extract metadata from a PDF file."""
        metadata = {
            'source': file_path,
            'file_type': 'pdf',
            'file_name': os.path.basename(file_path),
            'file_size': os.path.getsize(file_path),
            'pages': 0,
            'title': None,
            'author': None,
            'subject': None,
            'keywords': None,
            'created_date': None,
            'modified_date': None,
            'processing_timestamp': datetime.now(timezone.utc).isoformat(),
            'language': 'en',  # Default, can be detected
            'has_tables': False,
            'has_images': False,
            'is_scanned': False,
        }
        
        try:
            with open(file_path, 'rb') as file:
                reader = PdfReader(file)
                doc_info = reader.metadata
                
                metadata.update({
                    'pages': len(reader.pages),
                    'title': getattr(doc_info, 'title', None) or os.path.basename(file_path),
                    'author': getattr(doc_info, 'author', None),
                    'subject': getattr(doc_info, 'subject', None),
                    'keywords': getattr(doc_info, 'keywords', '').split(',') if getattr(doc_info, 'keywords', None) else [],
                    'created_date': str(getattr(doc_info, 'creation_date', None)),
                    'modified_date': str(getattr(doc_info, 'modification_date', None)),
                    'has_tables': any('/Table' in page.get('/Type', '') for page in reader.pages if hasattr(page, 'get')),
                    'is_scanned': self._is_scanned_pdf(reader)
                })
                
        except Exception as e:
            logger.warning(f"Could not extract all metadata from {file_path}: {str(e)}")
            
        return metadata
        
    def _safe_get_resources(self, page) -> dict:
        """Safely extract resources from a PDF page, handling IndirectObject."""
        try:
            if hasattr(page, 'get') and callable(page.get):
                resources = page.get('/Resources')
                if resources and hasattr(resources, 'get') and callable(resources.get):
                    return resources.get_object() if hasattr(resources, 'get_object') else {}
            return {}
        except Exception as e:
            logger.debug(f"Error getting resources: {str(e)}")
            return {}

    def _extract_text_from_pdf(self, file_path: str) -> Tuple[str, Dict[str, Any]]:
        """Extract text from a PDF file along with page-level metadata."""
        full_text = ""
        page_metadata = []
        
        try:
            with open(file_path, 'rb') as file:
                reader = PdfReader(file)
                
                for page_num, page in enumerate(reader.pages, 1):
                    try:
                        page_text = page.extract_text() or ""
                        full_text += page_text + "\n\n"
                        
                        # Get page resources safely
                        resources = self._safe_get_resources(page)
                        
                        # Extract page-level metadata
                        page_meta = {
                            'page_number': page_num,
                            'word_count': len(page_text.split()),
                            'has_form': '/Annots' in page,
                            'has_images': '/XObject' in resources,
                        }
                        
                        # Add section headers if found
                        headers = self._extract_headers(page_text)
                        if headers:
                            page_meta['section_headers'] = headers
                        
                        page_metadata.append(page_meta)
                        
                    except Exception as page_error:
                        logger.warning(f"Error processing page {page_num}: {str(page_error)}")
                        continue
                    
        except Exception as e:
            logger.error(f"Error extracting text from PDF: {str(e)}")
            raise
            
        return full_text.strip(), {'pages': page_metadata}

    def _is_scanned_pdf(self, pdf_reader) -> bool:
        """Check if PDF is scanned (image-based)."""
        try:
            for page in pdf_reader.pages:
                if '/Font' in page.get('/Resources', {}):
                    return False
            return len(pdf_reader.pages) > 0
        except:
            return False
            
    def _extract_headers(self, text: str) -> List[Dict[str, str]]:
        """Extract section headers from text."""
        headers = []
        lines = text.split('\n')
        
        for line in lines:
            line = line.strip()
            for pattern, header_type in self.header_patterns:
                if re.match(pattern, line):
                    headers.append({
                        'text': line,
                        'type': header_type,
                        'level': header_type.count('.') + 1  # For nested sections
                    })
                    break
                    
        return headers
        
    def _analyze_content(self, text: str) -> Dict[str, Any]:
        """Analyze text content for metadata extraction."""
        words = text.split()
        sentences = [s for s in re.split(r'[.!?]+', text) if s.strip()]
        
        return {
            'word_count': len(words),
            'sentence_count': len(sentences),
            'avg_word_length': sum(len(word) for word in words) / max(1, len(words)),
            'avg_sentence_length': sum(len(s.split()) for s in sentences) / max(1, len(sentences)) if sentences else 0,
            'contains_table': bool(re.search(r'\+[-=]+\+|\|.*\|', text)),
            'contains_list': bool(re.search(r'^\s*[\d•\-*]+\s+\w', text, re.MULTILINE)),
            'contains_code': bool(re.search(r'[{};=]|def\s+\w+\(|class\s+\w+', text)),
            'has_references': bool(re.search(r'references?\s*$', text[-100:], re.IGNORECASE)),
            'has_citations': bool(re.search(r'\[\d+\]|\([A-Za-z]+,\s*\d{4}\)', text)),
        }

    def _preprocess_text(self, text: str) -> str:
        """Clean and preprocess the extracted text."""
        if not text:
            return ""
            
        # Remove extra whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        
        # Remove page numbers and headers/footers
        text = re.sub(r'\n\d+\n', '\n', text)  # Page numbers on their own line
        text = re.sub(r'\b(?:page|pg\.?|p\.?)\s*\d+\b', '', text, flags=re.IGNORECASE)
        
        # Normalize newlines and spaces
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r' {2,}', ' ', text)
        
        # Clean up common PDF artifacts
        text = re.sub(r'\s*[-•*]\s*', ' ', text)  # Bullet points
        text = re.sub(r'\f', '\n', text)  # Form feeds
        
        return text

    def chunk_text(self, text: str, metadata: Optional[Dict] = None) -> List[Dict[str, Any]]:
        """
        Split a text string into chunks with optional metadata.
        
        Args:
            text: Input text to split
            metadata: Optional base metadata to include with each chunk
            
        Returns:
            List of document chunks with rich metadata
        """
        try:
            # Ensure we have base metadata
            base_metadata = {
                'source': 'text_input',
                'file_type': 'text/plain',
                'processing_timestamp': datetime.datetime.utcnow().isoformat(),
                'language': 'en',  # Could add language detection here
            }
            
            if metadata:
                base_metadata.update(metadata)
            
            # Pre-process text
            text = self._preprocess_text(text)
            
            # Analyze document structure
            headers = self._extract_headers(text)
            if headers:
                base_metadata['document_structure'] = {
                    'sections': [h['text'] for h in headers if h['type'] == 'section'],
                    'subsections': [h['text'] for h in headers if h['type'] == 'subsection'],
                    'total_sections': len([h for h in headers if h['type'] == 'section'])
                }
            
            # Split into chunks
            documents = self.text_splitter.create_documents([text])
            
            # Add metadata to chunks
            chunks = []
            for i, doc in enumerate(documents):
                chunk_meta = base_metadata.copy()
                chunk_content = doc.page_content
                
                # Add content analysis
                content_analysis = self._analyze_content(chunk_content)
                
                # Update chunk metadata
                chunk_meta.update({
                    'chunk_id': i,
                    'chunk_size': len(chunk_content),
                    'total_chunks': len(documents),
                    'chunk_start': text.find(chunk_content),
                    'chunk_end': text.find(chunk_content) + len(chunk_content),
                    'content_type': 'text/plain',
                    'processing_timestamp': datetime.datetime.utcnow().isoformat(),
                })
                
                # Add content analysis to metadata
                chunk_meta.update(content_analysis)
                
                # Determine which section this chunk belongs to
                if headers:
                    chunk_position = chunk_meta['chunk_start']
                    current_section = None
                    
                    for header in sorted(headers, key=lambda x: x.get('position', 0)):
                        if header.get('position', 0) <= chunk_position:
                            current_section = header
                    
                    if current_section:
                        chunk_meta['section'] = {
                            'title': current_section['text'],
                            'type': current_section['type'],
                            'level': current_section.get('level', 1)
                        }
                
                chunks.append({
                    'text': chunk_content,
                    'metadata': chunk_meta
                })
            
            logger.info(f"Split text into {len(chunks)} chunks with metadata")
            return chunks
            
        except Exception as e:
            logger.error(f"Error chunking text: {str(e)}")
            logger.exception("Detailed error:")
            raise

# Example usage
if __name__ == "__main__":
    # Initialize chunker
    chunker = DocumentChunker(
        chunk_size=1000,
        chunk_overlap=200
    )
    
    # Example: Chunk a PDF
    try:
        chunks = chunker.chunk_pdf(r"C:\Users\user\Desktop\metamed_backend\AHAACC2023Guidelines.pdf")
        for chunk in chunks:
            metadata = chunk['metadata']
            print(f"Chunk {metadata['chunk_id'] + 1}/{metadata['total_chunks']} ({len(chunk['text'])} chars)")
            print(f"Page: {metadata.get('page_number', 'N/A')}")
            print(f"Source: {metadata.get('source', 'N/A')}")
            print("-" * 50)
            print(chunk["text"][:200] + "...")  # Print first 200 chars of each chunk
            print("\n")
    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()