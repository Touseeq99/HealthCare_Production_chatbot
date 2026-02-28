"""
File Extractor Utility
=======================
Extracts clean clinical text from uploaded PDF or image files.

Two strategies:
  PDF  → PyPDF2 text layer first; if scanned (no text layer), falls back to
         GPT-4o Vision page-by-page.
  Image → GPT-4o Vision (handles handwritten notes, lab printouts, ECG strips,
          discharge summaries, referral letters, etc.)

Never stores files to disk — all processing is done on in-memory bytes.
"""

import io
import base64
import logging
from typing import Literal

from PyPDF2 import PdfReader
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv()

client = AsyncOpenAI()
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SUPPORTED_IMAGE_TYPES = {"image/jpeg", "image/jpg", "image/png", "image/webp", "image/gif"}
SUPPORTED_PDF_TYPES = {"application/pdf"}
SUPPORTED_MIME_TYPES = SUPPORTED_IMAGE_TYPES | SUPPORTED_PDF_TYPES

MAX_FILE_SIZE_MB = 10
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024

# GPT-4o Vision extraction prompt — instructs the model to act as a transcriber
VISION_EXTRACTION_PROMPT = """You are a medical document transcription assistant.
Your ONLY task is to extract and transcribe ALL readable text from the provided image exactly as it appears.

Rules:
- Transcribe ALL visible text, including handwritten content, printed text, tables, and labels.
- Preserve the original structure as much as possible (headings, lists, table rows).
- For lab reports: preserve test name, value, and reference range on the same line.
- For ECG strips: describe what you observe (rhythm, rate, any visible waveform annotations).
- Do NOT interpret, summarize, or add clinical opinions.
- Do NOT omit any text — completeness is critical.
- If a section is illegible, write: [ILLEGIBLE SECTION]
- Return plain text only — no markdown, no backticks."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _pdf_has_text_layer(pdf_bytes: bytes) -> bool:
    """Return True if at least one page has extractable text."""
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        for page in reader.pages:
            text = (page.extract_text() or "").strip()
            if len(text) > 30:   # More than a few stray chars → real text
                return True
        return False
    except Exception:
        return False


def _extract_text_from_pdf_bytes(pdf_bytes: bytes) -> str:
    """Extract text from a text-layer PDF into a single cleaned string."""
    reader = PdfReader(io.BytesIO(pdf_bytes))
    parts = []
    for i, page in enumerate(reader.pages, 1):
        page_text = (page.extract_text() or "").strip()
        if page_text:
            parts.append(f"[Page {i}]\n{page_text}")
    return "\n\n".join(parts).strip()


def _bytes_to_base64(data: bytes, mime_type: str) -> str:
    """Encode bytes as a base64 data URI for the OpenAI vision API."""
    encoded = base64.standard_b64encode(data).decode("utf-8")
    return f"data:{mime_type};base64,{encoded}"


async def _extract_text_via_vision(image_bytes: bytes, mime_type: str) -> str:
    """
    Send an image to GPT-4o Vision and return transcribed text.
    Used for: direct image uploads AND scanned/image-only PDFs (page-by-page).
    """
    data_uri = _bytes_to_base64(image_bytes, mime_type)
    response = await client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": VISION_EXTRACTION_PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {"url": data_uri, "detail": "high"},
                    },
                ],
            }
        ],
        temperature=0.0,
        max_tokens=4096,
    )
    return (response.choices[0].message.content or "").strip()


async def _extract_text_from_scanned_pdf(pdf_bytes: bytes) -> str:
    """
    Convert each PDF page to a PNG image using pdf2image, then run
    GPT-4o Vision on each page.  Falls back gracefully if pdf2image is
    unavailable (e.g. poppler not installed) by returning a clear warning.
    """
    try:
        from pdf2image import convert_from_bytes  # optional heavy dependency
    except ImportError:
        logger.warning("pdf2image not installed — scanned PDF OCR unavailable")
        return (
            "[WARNING: This PDF appears to be scanned (image-only) and has no "
            "extractable text layer. Install pdf2image and poppler to enable "
            "OCR on scanned PDFs, or paste the text manually.]"
        )

    try:
        images = convert_from_bytes(pdf_bytes, dpi=200, fmt="png")
    except Exception as exc:
        logger.error(f"pdf2image conversion failed: {exc}")
        return (
            "[WARNING: Could not convert scanned PDF pages to images. "
            f"Error: {exc}. Please paste the text content manually.]"
        )

    page_texts = []
    for i, pil_image in enumerate(images, 1):
        buf = io.BytesIO()
        pil_image.save(buf, format="PNG")
        page_bytes = buf.getvalue()
        logger.info(f"Running Vision OCR on scanned PDF page {i}/{len(images)}")
        page_text = await _extract_text_via_vision(page_bytes, "image/png")
        if page_text:
            page_texts.append(f"[Page {i}]\n{page_text}")

    return "\n\n".join(page_texts).strip()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

FileType = Literal["pdf", "image"]


def validate_upload(filename: str, content_type: str, file_size: int) -> None:
    """
    Validate an upload before processing.
    Raises ValueError with a user-friendly message on any violation.
    """
    if file_size > MAX_FILE_SIZE_BYTES:
        raise ValueError(
            f"File too large ({file_size / 1024 / 1024:.1f} MB). "
            f"Maximum allowed size is {MAX_FILE_SIZE_MB} MB."
        )

    ct = content_type.lower().split(";")[0].strip()  # Strip charset suffix
    if ct not in SUPPORTED_MIME_TYPES:
        raise ValueError(
            f"Unsupported file type '{content_type}'. "
            f"Supported types: PDF, JPEG, PNG, WEBP."
        )


async def extract_text_from_upload(
    file_bytes: bytes,
    content_type: str,
    filename: str = "upload",
) -> tuple[str, str]:
    """
    Extract clinical text from an uploaded PDF or image file.

    Parameters
    ----------
    file_bytes    : Raw file content as bytes
    content_type  : MIME type string (e.g. "application/pdf", "image/jpeg")
    filename      : Original filename for logging

    Returns
    -------
    (extracted_text, extraction_method) where extraction_method is one of:
      "pdf_text_layer"  — PyPDF2 direct extraction
      "pdf_vision_ocr"  — GPT-4o Vision on scanned PDF
      "image_vision"    — GPT-4o Vision on image
    """
    ct = content_type.lower().split(";")[0].strip()

    logger.info(
        f"Extracting text from upload",
        extra={"upload_filename": filename, "content_type": ct, "size_bytes": len(file_bytes)},
    )

    if ct == "application/pdf":
        if _pdf_has_text_layer(file_bytes):
            logger.info(f"PDF has text layer — using PyPDF2 extraction")
            text = _extract_text_from_pdf_bytes(file_bytes)
            return text, "pdf_text_layer"
        else:
            logger.info(f"PDF is scanned — falling back to Vision OCR")
            text = await _extract_text_from_scanned_pdf(file_bytes)
            return text, "pdf_vision_ocr"

    elif ct in SUPPORTED_IMAGE_TYPES:
        logger.info(f"Image upload — using GPT-4o Vision")
        text = await _extract_text_via_vision(file_bytes, ct)
        return text, "image_vision"

    else:
        raise ValueError(f"Unsupported content type: {content_type}")
