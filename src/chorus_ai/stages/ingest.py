from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from chorus_ai.artifacts.io import write_json
from chorus_ai.artifacts.validate import validate_artifact
from chorus_ai.core.config import load_run_config
from chorus_ai.core.errors import ChorusFatalError
from chorus_ai.runs.guards import require_missing
from chorus_ai.runs.status import require_state, set_state


_MIN_CHARS_PER_PAGE_DEFAULT = 50


def _extract_pages(pdf_path: Path) -> List[Dict[str, Any]]:
    """Extract text and structure from each page using pdfplumber."""
    try:
        import pdfplumber
    except ImportError as exc:
        raise ChorusFatalError(
            "MISSING_DEPENDENCY",
            "pdfplumber is not installed. Run: pip install pdfplumber",
            {},
        ) from exc

    pages_data: List[Dict[str, Any]] = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            raw_text: str = page.extract_text() or ""
            # Split into paragraphs on blank lines (double newline)
            raw_paragraphs = [p.strip() for p in raw_text.split("\n\n") if p.strip()]
            # Fallback: single-newline split if no blank-line structure found
            if not raw_paragraphs and raw_text.strip():
                raw_paragraphs = [p.strip() for p in raw_text.split("\n") if p.strip()]

            paragraphs = [
                {"para_idx": j, "text": p} for j, p in enumerate(raw_paragraphs)
            ]
            pages_data.append(
                {
                    "page_num": i + 1,
                    "char_count": len(raw_text),
                    "paragraph_count": len(paragraphs),
                    "paragraphs": paragraphs,
                }
            )

    return pages_data


def _build_document_text(pages_data: List[Dict[str, Any]]) -> str:
    """Build a single text file content with [PAGE N] markers for downstream LLM stages."""
    lines: List[str] = []
    for page in pages_data:
        lines.append(f"[PAGE {page['page_num']}]")
        for para in page["paragraphs"]:
            lines.append(para["text"])
            lines.append("")  # blank line between paragraphs
        lines.append("")  # extra blank line between pages
    return "\n".join(lines).strip()


def run_ingest(run_root: Path, source_doc_sha256: str, force: bool = False) -> None:
    """
    Stage 1: INGESTION

    Preconditions:
      - run state must be INIT
      - 00_input/input.pdf must exist in the run folder

    Postconditions:
      - 10_ingestion/document_text.txt written (paged text)
      - 10_ingestion/ingestion_record.json written and validated
      - run state becomes INGESTED

    Fails hard if:
      - PDF has no machine-readable text layer (image-only)
      - PDF cannot be opened or parsed
    """
    require_state(run_root, "INIT")

    pdf_path = run_root / "00_input" / "input.pdf"
    if not pdf_path.exists():
        raise ChorusFatalError(
            "INPUT_PDF_MISSING",
            "00_input/input.pdf not found in run folder",
            {"run_root": str(run_root)},
        )

    config = load_run_config(run_root)
    min_chars_per_page = (
        config.get("ingestion", {}).get("min_chars_per_page", _MIN_CHARS_PER_PAGE_DEFAULT)
    )

    out_dir = run_root / "10_ingestion"
    record_path = out_dir / "ingestion_record.json"
    text_path = out_dir / "document_text.txt"

    require_missing(record_path, force=force)

    # --- Extract text ---
    try:
        pages_data = _extract_pages(pdf_path)
    except ChorusFatalError:
        raise
    except Exception as exc:
        raise ChorusFatalError(
            "PDF_PARSE_ERROR",
            f"Failed to parse PDF: {exc}",
            {"pdf_path": str(pdf_path)},
        ) from exc

    page_count = len(pages_data)
    total_chars = sum(p["char_count"] for p in pages_data)

    # --- Text density validation ---
    avg_chars_per_page = total_chars / page_count if page_count > 0 else 0.0
    if avg_chars_per_page < min_chars_per_page:
        raise ChorusFatalError(
            "PDF_INELIGIBLE",
            (
                f"PDF rejected: average {avg_chars_per_page:.1f} chars/page "
                f"is below minimum {min_chars_per_page}. "
                "Document appears to be image-only or empty."
            ),
            {
                "avg_chars_per_page": avg_chars_per_page,
                "min_chars_per_page": min_chars_per_page,
                "page_count": page_count,
                "total_chars": total_chars,
            },
        )

    # --- Write document text ---
    document_text = _build_document_text(pages_data)
    text_path.write_text(document_text, encoding="utf-8")

    # --- Write ingestion record ---
    # Omit paragraphs from record for size; they're embedded in document_text.txt
    pages_summary = [
        {
            "page_num": p["page_num"],
            "char_count": p["char_count"],
            "paragraph_count": p["paragraph_count"],
        }
        for p in pages_data
    ]

    ingestion_record: Dict[str, Any] = {
        "schema_version": "v1",
        "source_doc_sha256": source_doc_sha256,
        "text_path": "10_ingestion/document_text.txt",
        "page_count": page_count,
        "total_chars": total_chars,
        "avg_chars_per_page": round(avg_chars_per_page, 2),
        "pages": pages_summary,
        "eligible": True,
    }

    validate_artifact("ingestion_record", ingestion_record)
    write_json(record_path, ingestion_record, force=force)

    set_state(run_root, "INGESTED")
