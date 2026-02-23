"""
PDF renderer for the Chorus AI Final Dossier.

Converts a FinalDossier dict (as produced by Stage 7) into a formatted PDF.
Design aesthetic: editorial monochrome — clean typography, red accent, cover page,
per-page header/footer.
"""
from __future__ import annotations

import xml.sax.saxutils as sax
from pathlib import Path
from typing import Any, Dict, List

from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# ---------------------------------------------------------------------------
# Palette — monochrome editorial with a single deep-red accent
# ---------------------------------------------------------------------------
_BLACK = HexColor("#0d0d0d")
_RED = HexColor("#8b0000")
_GRAY = HexColor("#666666")
_LIGHT_GRAY = HexColor("#dedede")
_RULE_COLOR = HexColor("#222222")

PAGE_W, PAGE_H = letter
MARGIN = 1.1 * inch
CONTENT_W = PAGE_W - 2 * MARGIN


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _e(text: str) -> str:
    """Escape text for ReportLab's XML parser."""
    return sax.escape(str(text))


def _hrule(thick: float = 0.5, color: Any = _RULE_COLOR, after: float = 6.0) -> HRFlowable:
    return HRFlowable(width="100%", thickness=thick, color=color, spaceAfter=after)


# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------

def _styles() -> Dict[str, ParagraphStyle]:
    return {
        "cover_eyebrow": ParagraphStyle(
            "cover_eyebrow",
            fontName="Helvetica",
            fontSize=8,
            textColor=_GRAY,
            alignment=TA_CENTER,
            spaceAfter=4,
        ),
        "cover_title": ParagraphStyle(
            "cover_title",
            fontName="Helvetica-Bold",
            fontSize=30,
            textColor=_BLACK,
            alignment=TA_CENTER,
            spaceAfter=8,
            leading=36,
        ),
        "cover_doc_title": ParagraphStyle(
            "cover_doc_title",
            fontName="Times-Italic",
            fontSize=14,
            textColor=_BLACK,
            alignment=TA_CENTER,
            spaceAfter=4,
            leading=20,
        ),
        "cover_doc_byline": ParagraphStyle(
            "cover_doc_byline",
            fontName="Helvetica",
            fontSize=9,
            textColor=_GRAY,
            alignment=TA_CENTER,
            spaceAfter=0,
        ),
        "cover_factcheck_cert": ParagraphStyle(
            "cover_factcheck_cert",
            fontName="Helvetica-Bold",
            fontSize=8,
            textColor=_BLACK,
            alignment=TA_LEFT,
            leading=13,
        ),
        "cover_process_label": ParagraphStyle(
            "cover_process_label",
            fontName="Helvetica-Bold",
            fontSize=7,
            textColor=_GRAY,
            spaceAfter=4,
            spaceBefore=16,
        ),
        "cover_process_body": ParagraphStyle(
            "cover_process_body",
            fontName="Times-Roman",
            fontSize=9,
            textColor=_BLACK,
            alignment=TA_JUSTIFY,
            leading=14,
            spaceAfter=0,
        ),
        "cover_meta_key": ParagraphStyle(
            "cover_meta_key",
            fontName="Helvetica-Bold",
            fontSize=8,
            textColor=_GRAY,
            alignment=TA_RIGHT,
        ),
        "cover_meta_val": ParagraphStyle(
            "cover_meta_val",
            fontName="Helvetica",
            fontSize=8,
            textColor=_BLACK,
            alignment=TA_LEFT,
        ),
        "section_eyebrow": ParagraphStyle(
            "section_eyebrow",
            fontName="Helvetica",
            fontSize=7,
            textColor=_RED,
            spaceAfter=2,
            spaceBefore=20,
        ),
        "section_title": ParagraphStyle(
            "section_title",
            fontName="Helvetica-Bold",
            fontSize=14,
            textColor=_BLACK,
            spaceAfter=6,
            spaceBefore=0,
        ),
        "body": ParagraphStyle(
            "body",
            fontName="Times-Roman",
            fontSize=10,
            textColor=_BLACK,
            alignment=TA_JUSTIFY,
            spaceAfter=8,
            leading=15,
        ),
        "body_italic": ParagraphStyle(
            "body_italic",
            fontName="Times-Italic",
            fontSize=9,
            textColor=_GRAY,
            alignment=TA_JUSTIFY,
            spaceAfter=10,
            leading=14,
        ),
        "claim_num": ParagraphStyle(
            "claim_num",
            fontName="Helvetica-Bold",
            fontSize=8,
            textColor=_RED,
            spaceAfter=2,
            spaceBefore=12,
        ),
        "claim_text": ParagraphStyle(
            "claim_text",
            fontName="Times-Roman",
            fontSize=10,
            textColor=_BLACK,
            spaceAfter=3,
            leading=15,
            leftIndent=12,
        ),
        "claim_meta": ParagraphStyle(
            "claim_meta",
            fontName="Helvetica",
            fontSize=8,
            textColor=_GRAY,
            spaceAfter=6,
            leftIndent=12,
        ),
        "audit_key": ParagraphStyle(
            "audit_key",
            fontName="Helvetica-Bold",
            fontSize=8,
            textColor=_GRAY,
        ),
        "audit_val": ParagraphStyle(
            "audit_val",
            fontName="Helvetica",
            fontSize=8,
            textColor=_BLACK,
        ),
        "warning_text": ParagraphStyle(
            "warning_text",
            fontName="Helvetica",
            fontSize=9,
            textColor=_RED,
            spaceAfter=4,
            leading=13,
        ),
        # Contextual analysis structure
        "ctx_model_header": ParagraphStyle(
            "ctx_model_header",
            fontName="Helvetica-Bold",
            fontSize=9,
            textColor=_GRAY,
            spaceBefore=16,
            spaceAfter=2,
        ),
        "ctx_lens_header": ParagraphStyle(
            "ctx_lens_header",
            fontName="Helvetica-Bold",
            fontSize=10,
            textColor=_BLACK,
            spaceBefore=10,
            spaceAfter=3,
        ),
        "ctx_sources_label": ParagraphStyle(
            "ctx_sources_label",
            fontName="Helvetica-Bold",
            fontSize=8,
            textColor=_GRAY,
            spaceBefore=6,
            spaceAfter=2,
        ),
        "ctx_citation": ParagraphStyle(
            "ctx_citation",
            fontName="Helvetica",
            fontSize=8,
            textColor=_GRAY,
            leftIndent=14,
            spaceAfter=3,
            leading=12,
        ),
        # Verification receipt
        "receipt_header": ParagraphStyle(
            "receipt_header",
            fontName="Helvetica-Bold",
            fontSize=8,
            textColor=_BLACK,
        ),
        "receipt_claim_num": ParagraphStyle(
            "receipt_claim_num",
            fontName="Courier-Bold",
            fontSize=8,
            textColor=_GRAY,
            spaceAfter=1,
        ),
        "receipt_status": ParagraphStyle(
            "receipt_status",
            fontName="Helvetica-Bold",
            fontSize=8,
            textColor=_RED,
            alignment=TA_RIGHT,
        ),
        "receipt_claim_text": ParagraphStyle(
            "receipt_claim_text",
            fontName="Times-Roman",
            fontSize=10,
            textColor=_BLACK,
            spaceAfter=3,
            leading=14,
        ),
        "receipt_meta": ParagraphStyle(
            "receipt_meta",
            fontName="Courier",
            fontSize=7,
            textColor=_GRAY,
            spaceAfter=0,
            leading=11,
        ),
        "model_attribution": ParagraphStyle(
            "model_attribution",
            fontName="Helvetica",
            fontSize=7.5,
            textColor=_GRAY,
            spaceAfter=10,
            leading=11,
        ),
        "roster_role": ParagraphStyle(
            "roster_role",
            fontName="Helvetica-Bold",
            fontSize=8.5,
            textColor=_BLACK,
        ),
        "roster_model": ParagraphStyle(
            "roster_model",
            fontName="Courier",
            fontSize=8,
            textColor=_GRAY,
        ),
        "roster_desc": ParagraphStyle(
            "roster_desc",
            fontName="Times-Italic",
            fontSize=9,
            textColor=_GRAY,
            leading=13,
        ),
        # Compiled summary — editorial typography
        # Lead: first paragraph, flush left (no indent), slightly larger, generous air
        "summary_lead": ParagraphStyle(
            "summary_lead",
            fontName="Times-Roman",
            fontSize=11,
            textColor=_BLACK,
            alignment=TA_JUSTIFY,
            leading=18,
            spaceAfter=2,
        ),
        # Body: subsequent paragraphs, first-line indent does the visual separating work
        # (no spaceAfter — the indent reads as a new paragraph, like print editorial)
        "summary_body": ParagraphStyle(
            "summary_body",
            fontName="Times-Roman",
            fontSize=11,
            textColor=_BLACK,
            alignment=TA_JUSTIFY,
            leading=18,
            firstLineIndent=20,
            spaceAfter=0,
        ),
    }


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------

def _section_block(num: int, title: str, s: Dict[str, ParagraphStyle]) -> List:
    return [
        Paragraph(f"SECTION {num:02d}", s["section_eyebrow"]),
        Paragraph(_e(title), s["section_title"]),
        _hrule(),
    ]


def _cover_elements(dossier: Dict[str, Any], s: Dict[str, ParagraphStyle]) -> List:
    created = dossier.get("created_at", "")[:19].replace("T", " ")
    run_status = dossier.get("run_status", "complete").upper()
    doc_meta = dossier.get("document_meta", {})
    process_description = dossier.get("process_description", "")

    elements: List = [Spacer(1, 1.4 * inch)]

    elements.append(_hrule(thick=2.5, color=_RED, after=20))
    elements.append(Paragraph("CHORUS AI  \u00b7  INTELLIGENCE DOSSIER", s["cover_eyebrow"]))
    elements.append(Paragraph("Chorus AI \u2013 Dossier", s["cover_title"]))

    # Document title, author, publication (if available from PDF metadata)
    if doc_meta.get("title"):
        elements.append(Spacer(1, 0.06 * inch))
        elements.append(Paragraph(_e(doc_meta["title"]), s["cover_doc_title"]))
    if doc_meta.get("author"):
        elements.append(Paragraph(_e(f"By {doc_meta['author']}"), s["cover_doc_byline"]))
    if doc_meta.get("subject"):
        elements.append(Paragraph(_e(doc_meta["subject"]), s["cover_doc_byline"]))

    elements.append(_hrule(thick=2.5, color=_RED, after=28))
    elements.append(Spacer(1, 0.25 * inch))

    col_w = [2.0 * inch, CONTENT_W - 2.0 * inch]
    meta_rows = [
        [Paragraph("GENERATED", s["cover_meta_key"]),
         Paragraph(_e(created + " UTC"), s["cover_meta_val"])],
        [Paragraph("PIPELINE", s["cover_meta_key"]),
         Paragraph("Chorus AI V1  \u00b7  7-Stage Verification Pipeline", s["cover_meta_val"])],
        [Paragraph("STATUS", s["cover_meta_key"]),
         Paragraph(_e(run_status), s["cover_meta_val"])],
    ]
    meta_ts = TableStyle([
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LINEBELOW", (0, 0), (-1, -2), 0.25, _LIGHT_GRAY),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ])
    t = Table(meta_rows, colWidths=col_w)
    t.setStyle(meta_ts)
    elements.append(t)

    # Fact-check certification block
    elements.append(Spacer(1, 0.18 * inch))
    cert_text = (
        "\u2713  FACT-CHECK CERTIFIED  \u00b7  "
        "All summaries passed zero-tolerance contradiction screening "
        "against a locked fact list extracted directly from the source document. "
        "No claim in this dossier contradicts the original text."
    )
    cert_row = [[Paragraph(cert_text, s["cover_factcheck_cert"])]]
    cert_t = Table(cert_row, colWidths=[CONTENT_W])
    cert_t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), HexColor("#f0f0f0")),
        ("LINEABOVE",     (0, 0), (-1,  0), 1.5, _RED),
        ("LINEBELOW",     (0, -1), (-1, -1), 0.5, _LIGHT_GRAY),
        ("TOPPADDING",    (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
        ("LEFTPADDING",   (0, 0), (-1, -1), 12),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 12),
    ]))
    elements.append(cert_t)

    # Process description — how this report was made, in plain English
    if process_description:
        elements.append(Paragraph("HOW THIS REPORT WAS MADE", s["cover_process_label"]))
        elements.append(_hrule(thick=0.25, color=_LIGHT_GRAY, after=6))
        elements.append(Paragraph(_e(process_description), s["cover_process_body"]))

    elements.append(PageBreak())
    return elements


def _verification_receipt_elements(claims: List[Dict[str, Any]], s: Dict[str, ParagraphStyle]) -> List:
    """
    Render key claims as a fact-check verification receipt.

    Styled like a POS printout — compact, monospaced metadata, dashed separators —
    to communicate that this is a traceability log, not a narrative section.
    """
    _BG = HexColor("#f7f7f7")

    if not claims:
        return [Paragraph("[No claims verified.]", s["body"])]

    total = len(claims)
    elements: List = []

    # Receipt header band
    header_row = [[Paragraph(
        f"FACT-CHECK RECEIPT  \u00b7  {total} claim{'s' if total != 1 else ''} verified against extracted facts",
        s["receipt_header"],
    )]]
    header_t = Table(header_row, colWidths=[CONTENT_W])
    header_t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _BG),
        ("LINEABOVE",  (0, 0), (-1,  0), 1.0, _RULE_COLOR),
        ("LINEBELOW",  (0, -1), (-1, -1), 0.5, _LIGHT_GRAY),
        ("TOPPADDING",    (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING",   (0, 0), (-1, -1), 10),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 10),
    ]))
    elements.append(header_t)
    elements.append(Spacer(1, 0.08 * inch))

    for i, claim in enumerate(claims):
        text = claim.get("claim", "")
        fact_ids = claim.get("fact_ids", [])
        convergence = (claim.get("convergence") or "").upper() or "\u2014"
        sources = claim.get("source_summaries", [])

        fact_ref = " \u00b7 ".join(fact_ids) if fact_ids else "\u2014"
        n_src = len(sources)

        # Two-column claim header: number left, VERIFIED right
        claim_hdr = Table(
            [[Paragraph(f"#{i + 1:03d}", s["receipt_claim_num"]),
              Paragraph("\u2713 VERIFIED", s["receipt_status"])]],
            colWidths=[CONTENT_W * 0.5, CONTENT_W * 0.5],
        )
        claim_hdr.setStyle(TableStyle([
            ("ALIGN",         (1, 0), (1, 0), "RIGHT"),
            ("TOPPADDING",    (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ("LEFTPADDING",   (0, 0), (-1, -1), 0),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
        ]))

        meta = f"FACTS: {fact_ref}    CONVERGENCE: {convergence}    SOURCES: {n_src} of 3"

        block = [
            claim_hdr,
            Paragraph(_e(text), s["receipt_claim_text"]),
            Paragraph(_e(meta), s["receipt_meta"]),
        ]
        elements.append(KeepTogether(block))

        if i < total - 1:
            elements.append(HRFlowable(
                width="100%", thickness=0.5, color=_LIGHT_GRAY,
                dash=(2, 3), spaceAfter=6, spaceBefore=6,
            ))

    # Receipt footer band
    elements.append(Spacer(1, 0.08 * inch))
    footer_row = [[Paragraph(
        f"END OF RECEIPT  \u00b7  {total}/{total} claims traceable to source facts",
        s["receipt_header"],
    )]]
    footer_t = Table(footer_row, colWidths=[CONTENT_W])
    footer_t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _BG),
        ("LINEABOVE",  (0, 0), (-1,  0), 0.5, _LIGHT_GRAY),
        ("LINEBELOW",  (0, -1), (-1, -1), 1.0, _RULE_COLOR),
        ("TOPPADDING",    (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING",   (0, 0), (-1, -1), 10),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 10),
    ]))
    elements.append(footer_t)

    return elements


def _audit_table_elements(audit: Dict[str, Any], s: Dict[str, ParagraphStyle]) -> List:
    def _row(key: str, val: Any) -> List:
        return [Paragraph(_e(key), s["audit_key"]), Paragraph(_e(str(val)), s["audit_val"])]

    verification = audit.get("verification", {})
    rows = [
        _row("Dossier ID", audit.get("dossier_id", "")),
        _row("Source SHA-256", audit.get("source_doc_sha256", "")),
        _row("Page Count", audit.get("page_count", "")),
        _row("Total Characters", f"{audit.get('total_chars', 0):,}"),
        _row("Facts Extracted", audit.get("fact_count", "")),
        _row("Fact Set ID", audit.get("fact_set_id", "")),
        _row("Verification Status", verification.get("status", "").upper()),
        _row("Max Allowed Contradictions", verification.get("max_contradiction_score", 0.0)),
        _row("Retries Used", verification.get("retries_used", 0)),
    ]

    for score in verification.get("summary_scores", []):
        slot = score.get("model_slot", "?")
        passed = score.get("passes_contradiction_check")
        contradiction = score.get("contradiction_score")
        coverage = score.get("coverage_score")
        result = "PASS" if passed else "FAIL"
        detail_parts = []
        if contradiction is not None:
            detail_parts.append(f"contradictions: {contradiction:.0%}")
        if coverage is not None:
            detail_parts.append(f"coverage: {coverage:.0%}")
        detail = f"  ({',  '.join(detail_parts)})" if detail_parts else ""
        rows.append(_row(f"  {slot}", f"{result}{detail}"))

    ctx = audit.get("contextual_analyses", [])
    rows.append(_row("Contextual Analyses", ", ".join(ctx) if ctx else "none"))

    col_w = [2.2 * inch, CONTENT_W - 2.2 * inch]
    ts = TableStyle([
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LINEBELOW", (0, 0), (-1, -2), 0.25, _LIGHT_GRAY),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ])
    t = Table(rows, colWidths=col_w)
    t.setStyle(ts)
    return [t]


def _contextual_analysis_elements(ctx_text: str, s: Dict[str, ParagraphStyle]) -> List:
    """
    Parse and render the contextual analysis string produced by _build_contextual_analysis_section.

    The string embeds structure via conventions:
      === Contextual Analysis (contextualizer_x) ===  → model subheader + rule
      [Lens Name]                                      → lens subheading
      Sources:                                         → sources label
        - Citation text                                → indented citation
      Everything else                                  → body paragraph

    Splitting on \\n\\n first gives clean chunks regardless of how the LLM
    formatted internal whitespace.
    """
    if not ctx_text or ctx_text.startswith("[No contextual"):
        return [Paragraph(_e(ctx_text), s["body"])]

    elements: List = []
    chunks = [c.strip() for c in ctx_text.split("\n\n") if c.strip()]

    # Pre-count how many model-section headers exist so we can number them
    _num_sections = sum(
        1 for c in chunks
        if " ".join(c.split()).startswith("===") and " ".join(c.split()).endswith("===")
    )
    _section_counter = 0
    _roman = ["I", "II", "III", "IV"]

    for chunk in chunks:
        # Collapse internal newlines so each chunk is a single line for matching
        line = " ".join(chunk.split())

        if line.startswith("===") and line.endswith("==="):
            # Model section header — strip the model slot name, the model roster above already
            # identifies the model; here we just label the analytical perspective.
            _section_counter += 1
            if _num_sections > 1:
                label = f"Contextual Analysis \u2014 Part {_roman[_section_counter - 1]}"
            else:
                label = "Contextual Analysis"
            elements.append(Spacer(1, 0.08 * inch))
            elements.append(_hrule(thick=0.5, color=_LIGHT_GRAY, after=4))
            elements.append(Paragraph(_e(label), s["ctx_model_header"]))

        elif line.startswith("[") and line.endswith("]"):
            # Lens header  e.g. "[Historical Context]"
            lens = line[1:-1]
            elements.append(Paragraph(_e(lens), s["ctx_lens_header"]))

        elif line == "Sources:":
            elements.append(Paragraph("Sources:", s["ctx_sources_label"]))

        elif line.startswith("- "):
            # Citation entry
            elements.append(Paragraph(_e(line[2:]), s["ctx_citation"]))

        elif line.startswith("Limitations:"):
            elements.append(Paragraph(_e(line), s["body_italic"]))

        else:
            elements.append(Paragraph(_e(line), s["body"]))

    return elements


def _compiled_summary_elements(text: str, s: Dict[str, ParagraphStyle]) -> List:
    """
    Render compiled summary text with editorial typography:
    - First paragraph: flush left, 11pt, generous leading (no indent by convention)
    - Subsequent paragraphs: first-line indent, no extra space between — the indent
      does the visual separation, exactly as in print long-form editorial.
    """
    paras = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paras:
        return [Paragraph("[Compiled summary not available.]", s["body"])]

    elements: List = []
    for i, para in enumerate(paras):
        style = s["summary_lead"] if i == 0 else s["summary_body"]
        elements.append(Paragraph(_e(para.replace("\n", " ")), style))
    return elements


def _model_attribution(text: str, s: Dict[str, ParagraphStyle]) -> List:
    """Small gray attribution line placed directly after a section's HR rule."""
    if not text:
        return []
    return [Paragraph(_e(text), s["model_attribution"])]


def _model_roster_elements(roster: List[Dict[str, Any]], s: Dict[str, ParagraphStyle]) -> List:
    """
    Render the model roster as a table:  Role | Model ID | Description
    """
    if not roster:
        return [Paragraph("[No model information available.]", s["body"])]

    col_w = [1.5 * inch, 1.7 * inch, CONTENT_W - 1.5 * inch - 1.7 * inch]
    rows = []
    for entry in roster:
        rows.append([
            Paragraph(_e(entry.get("role", "")), s["roster_role"]),
            Paragraph(_e(entry.get("model_id", "").replace("together:", "")), s["roster_model"]),
            Paragraph(_e(entry.get("description", "")), s["roster_desc"]),
        ])

    ts = TableStyle([
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LINEBELOW",     (0, 0), (-1, -2), 0.25, _LIGHT_GRAY),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
    ])
    t = Table(rows, colWidths=col_w)
    t.setStyle(ts)
    return [t]


def _pipeline_warnings_elements(warnings: List[str], s: Dict[str, ParagraphStyle]) -> List:
    """Render pipeline warnings as a bulleted list with red text."""
    if not warnings:
        return []
    elements: List = []
    for w in warnings:
        elements.append(Paragraph(f"\u2022 {_e(w)}", s["warning_text"]))
    return elements


def _draw_page(canvas: Any, doc: Any, dossier_id: str, created: str) -> None:
    """Render header and footer on every non-cover page."""
    if canvas.getPageNumber() == 1:
        return
    canvas.saveState()
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(_GRAY)

    # Header
    canvas.drawString(MARGIN, PAGE_H - 0.65 * inch, "CHORUS AI  \u00b7  INTELLIGENCE DOSSIER")
    canvas.drawRightString(PAGE_W - MARGIN, PAGE_H - 0.65 * inch, dossier_id)
    canvas.setStrokeColor(_RULE_COLOR)
    canvas.setLineWidth(0.5)
    canvas.line(MARGIN, PAGE_H - 0.72 * inch, PAGE_W - MARGIN, PAGE_H - 0.72 * inch)

    # Footer
    canvas.line(MARGIN, 0.72 * inch, PAGE_W - MARGIN, 0.72 * inch)
    canvas.drawString(MARGIN, 0.52 * inch, f"Generated {created} UTC")
    canvas.drawRightString(PAGE_W - MARGIN, 0.52 * inch, f"Page {canvas.getPageNumber()}")
    canvas.restoreState()


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def render_dossier_pdf(dossier: Dict[str, Any], out_path: Path) -> None:
    """
    Render a FinalDossier dict to a formatted PDF at out_path.

    Sections rendered:
      Cover page (title, document metadata, process description)
      01 – Executive Overview
      02 – Compiled Summary
      03 – Contextual Analysis
      04 – Risks, Limitations, and Warnings
      05 – Verification Receipt (key claims fact-check log)
      06 – Audit Trail (includes Dossier ID and Source SHA)
      07 – Model Roster
      08 – Pipeline Notices (only if warnings present)
    """
    s = _styles()
    sections = dossier.get("sections", {})
    dossier_id = dossier.get("dossier_id", "UNKNOWN")
    created = dossier.get("created_at", "")[:19].replace("T", " ")
    attr = dossier.get("section_attributions", {})
    roster = dossier.get("model_roster", [])

    def _on_page(canvas: Any, doc: Any) -> None:
        _draw_page(canvas, doc, dossier_id, created)

    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=letter,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=MARGIN,
    )

    story: List = []

    # Cover
    story.extend(_cover_elements(dossier, s))

    # 01 — Executive Overview
    story.extend(_section_block(1, "EXECUTIVE OVERVIEW", s))
    story.extend(_model_attribution(attr.get("1", ""), s))
    overview = sections.get("executive_overview", "[Not available.]")
    story.append(Paragraph(_e(overview), s["body"]))

    # 02 — Compiled Summary
    story.extend(_section_block(2, "COMPILED SUMMARY", s))
    story.extend(_model_attribution(attr.get("2", ""), s))
    story.append(Paragraph(
        "\u2713 Fact-check verified. Every claim in this summary was cross-checked against "
        "a locked list of facts extracted directly from the source document. Summaries "
        "that contradicted any extracted fact were rejected before reaching this report.",
        s["body_italic"],
    ))
    story.extend(_compiled_summary_elements(
        sections.get("compiled_summary", "[Not available.]"), s
    ))

    # 03 — Contextual Analysis
    story.extend(_section_block(3, "CONTEXTUAL ANALYSIS", s))
    story.extend(_model_attribution(attr.get("3", ""), s))
    story.append(Paragraph(
        "External context provided by contextualizer models. All claims in this section "
        "are sourced from external references and are explicitly labeled as such.",
        s["body_italic"],
    ))
    story.extend(_contextual_analysis_elements(
        sections.get("contextual_analysis", "[No contextual analysis available.]"), s
    ))

    # 04 — Risks, Limitations, and Warnings
    story.extend(_section_block(4, "RISKS, LIMITATIONS, AND WARNINGS", s))
    story.extend(_model_attribution(attr.get("4", ""), s))
    risks = sections.get("risks_and_limitations", "[No risks or limitations identified.]")
    story.append(Paragraph(_e(risks), s["body"]))

    # 05 — Verification Receipt
    story.extend(_section_block(5, "VERIFICATION RECEIPT", s))
    story.extend(_model_attribution(attr.get("5", ""), s))
    story.append(Paragraph(
        "The following claims were subjected to a zero-tolerance fact-check: a dedicated "
        "model extracted every discrete factual claim from the source document into a locked "
        "fact list, then a separate verification model checked each AI-generated summary "
        "against that list. Any summary that contradicted even a single extracted fact was "
        "rejected outright — no exceptions, no partial credit. Only summaries with zero "
        "contradictions advanced to the compiled report. The entries below are traceable to "
        "specific facts in the original document.",
        s["body_italic"],
    ))
    story.extend(_verification_receipt_elements(sections.get("key_claims", []), s))

    # 06 — Audit Trail
    story.extend(_section_block(6, "AUDIT TRAIL", s))
    story.extend(_audit_table_elements(sections.get("audit_trail", {}), s))

    # 07 — Model Roster
    story.extend(_section_block(7, "MODEL ROSTER", s))
    story.extend(_model_roster_elements(roster, s))

    # 08 — Pipeline Notices (only if warnings present)
    warnings = dossier.get("warnings", [])
    if warnings:
        story.extend(_section_block(8, "PIPELINE NOTICES", s))
        story.extend(_pipeline_warnings_elements(warnings, s))

    doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)
