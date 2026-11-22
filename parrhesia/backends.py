"""Optional pluggable parser and scientific-math backends with pure-stdlib defaults.

The Parrhesia runtime never requires third-party packages. When optional libraries
(e.g. PyMuPDF/pypdf for complex modern PDFs, SciPy for exact statistics) are installed
in the host Python environment, this module exposes bounded, read-only adapters and
reports the active backend transparently rather than hiding provenance.
"""
from __future__ import annotations

import importlib.util
from typing import Any

from .contracts import ContractError, fail

MAX_PDF_CHARS = 1_000_000


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def available_backends() -> dict[str, dict[str, Any]]:
    """Report optional parsing and statistical acceleration backends without importing heavy modules eagerly."""
    has_fitz = _module_available("fitz")
    has_pypdf = _module_available("pypdf")
    has_scipy = _module_available("scipy")
    return {
        "pdf": {
            "default": "stdlib_pdf",
            "optional_available": [
                name for name, ok in (("pymupdf", has_fitz), ("pypdf", has_pypdf)) if ok
            ],
            "active_fallback": "optional_pymupdf" if has_fitz else "optional_pypdf" if has_pypdf else None,
        },
        "statistics": {
            "default": "stdlib_math",
            "optional_available": ["scipy"] if has_scipy else [],
            "active_accelerator": "optional_scipy" if has_scipy else None,
        },
    }


def extract_pdf_with_fallback(
    content: bytes,
    *,
    allow_optional_backend: bool = False,
) -> tuple[list[dict[str, Any]], list[str], str]:
    """Try pure-stdlib PDF extraction first; optionally fall back to PyMuPDF/pypdf for unsupported PDFs.

    Returns (units, omitted, parser_backend). Never executes embedded scripts, never runs
    OCR on images, and always records `parser_backend` and explicit `omitted` caveats honestly.
    """
    from .pdf_reader import extract_pdf

    try:
        units, omitted = extract_pdf(content)
        return units, omitted, "stdlib_pdf"
    except ContractError as stdlib_exc:
        if not allow_optional_backend or stdlib_exc.code not in ("unsupported_format", "invalid_source"):
            raise
        if b"/Encrypt" in content:
            raise
        fallback = _try_optional_pdf_backends(content, stdlib_exc)
        if fallback is None:
            raise
        return fallback


def _try_optional_pdf_backends(content: bytes, original_error: ContractError) -> tuple[list[dict[str, Any]], list[str], str] | None:
    if _module_available("fitz"):
        return _extract_with_pymupdf(content, original_error)
    if _module_available("pypdf"):
        return _extract_with_pypdf(content, original_error)
    return None


def _extract_with_pymupdf(content: bytes, original_error: ContractError) -> tuple[list[dict[str, Any]], list[str], str]:
    import fitz  # type: ignore[import-not-found]

    try:
        doc = fitz.open(stream=content, filetype="pdf")
    except Exception as exc:
        fail("invalid_source", f"Optional PyMuPDF fallback could not open PDF: {exc.__class__.__name__}")
    try:
        if getattr(doc, "is_encrypted", False):
            fail("unsupported_format", "Encrypted PDFs are not supported")
        units: list[dict[str, Any]] = []
        omitted: list[str] = [
            f"stdlib_pdf_rejected:{original_error.code}",
            "pdf_images_and_ocr_not_run",
        ]
        total_chars = 0
        for page_index, page in enumerate(doc, start=1):
            text = (page.get_text("text") or "").strip()
            if not text:
                continue
            total_chars += len(text)
            if total_chars > MAX_PDF_CHARS:
                fail("too_large", "Extracted PDF text exceeds 1,000,000 characters")
            units.append({"text": text, "location": f"page:{page_index}"})
        if not units:
            fail("invalid_source", "PDF contains no extractable text via optional PyMuPDF backend")
        return units, omitted, "optional_pymupdf"
    finally:
        doc.close()


def _extract_with_pypdf(content: bytes, original_error: ContractError) -> tuple[list[dict[str, Any]], list[str], str]:
    import io
    from pypdf import PdfReader  # type: ignore[import-not-found]

    try:
        reader = PdfReader(io.BytesIO(content))
    except Exception as exc:
        fail("invalid_source", f"Optional pypdf fallback could not open PDF: {exc.__class__.__name__}")
    if getattr(reader, "is_encrypted", False):
        fail("unsupported_format", "Encrypted PDFs are not supported")
    units: list[dict[str, Any]] = []
    omitted: list[str] = [
        f"stdlib_pdf_rejected:{original_error.code}",
        "pdf_images_and_ocr_not_run",
    ]
    total_chars = 0
    for page_index, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if not text:
            continue
        total_chars += len(text)
        if total_chars > MAX_PDF_CHARS:
            fail("too_large", "Extracted PDF text exceeds 1,000,000 characters")
        units.append({"text": text, "location": f"page:{page_index}"})
    if not units:
        fail("invalid_source", "PDF contains no extractable text via optional pypdf backend")
    return units, omitted, "optional_pypdf"
